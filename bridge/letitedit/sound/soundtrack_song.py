"""The song analysed: beats, bars, sections, energy and musical events.

Part of `soundtrack` (letitedit/sound/soundtrack.py), which imports every name here back,
so `soundtrack.X` is the same object it always was.
"""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import numpy as np
from letitedit.sound.soundtrack_base import (  # noqa: E402
    ANALYSIS_VERSION, HOP, MSR, N_FFT, SR, WORK, _LOCK, _MEM, _clock, _decode, _json_write, _span
)


# ============================================================================ song analysis

def _mel_fb(sr, n_fft, n_mels=40, fmin=40.0, fmax=8000.0):
    def hz2mel(f):
        return 2595.0 * np.log10(1.0 + f / 700.0)

    def mel2hz(m):
        return 700.0 * (10 ** (m / 2595.0) - 1.0)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    hz = mel2hz(np.linspace(hz2mel(fmin), hz2mel(min(fmax, sr / 2)), n_mels + 2))
    fb = np.zeros((n_mels, len(freqs)), np.float32)
    for m in range(n_mels):
        lo, c, hi = hz[m], hz[m + 1], hz[m + 2]
        fb[m] = np.maximum(0.0, np.minimum((freqs - lo) / (c - lo), (hi - freqs) / (hi - c)))
    return fb


def _chroma_fb(sr, n_fft, fmin=55.0, fmax=4000.0):
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    fb = np.zeros((12, len(freqs)), np.float32)
    midi = 69 + 12 * np.log2(np.maximum(freqs, 1e-6) / 440.0)
    lo = np.floor(midi)
    frac = midi - lo
    for k in np.flatnonzero((freqs >= fmin) & (freqs <= fmax)):
        a = int(lo[k]) % 12
        fb[a, k] += 1 - frac[k]
        fb[(a + 1) % 12, k] += frac[k]
    return fb


def _frame_features(y, sr=SR, n_fft=N_FFT, hop=HOP):
    """log-mel (40 bands) and chroma (12) per analysis frame; frame k is centred at k * hop / sr."""
    mel_fb, ch_fb = _mel_fb(sr, n_fft), _chroma_fb(sr, n_fft)
    pad = n_fft // 2
    yp = np.pad(np.asarray(y, np.float32), (pad, pad))
    n = max(0, 1 + (len(yp) - n_fft) // hop)
    win = np.hanning(n_fft).astype(np.float32)
    mel = np.empty((n, mel_fb.shape[0]), np.float32)
    chroma = np.empty((n, 12), np.float32)
    offs = np.arange(n_fft)
    for s in range(0, n, 1024):
        e = min(n, s + 1024)
        P = np.abs(np.fft.rfft(yp[np.arange(s, e)[:, None] * hop + offs[None, :]] * win, axis=1)) ** 2
        mel[s:e] = np.log10(P @ mel_fb.T + 1e-9)
        chroma[s:e] = P @ ch_fb.T
    return mel, chroma


def _clarity(env, fps, period):
    """(salience, stability): the onset envelope's normalized autocorrelation at the beat period, and the share of
    12 s windows whose own strongest periodicity (55-200 bpm) agrees with the period (or half / double it)."""
    if period <= 1 or len(env) < 4 * period:
        return 0.0, 0.0
    e = env - env.mean()
    ac = np.correlate(e, e, mode='full')[len(e) - 1:]
    ac = ac / (ac[0] + 1e-12)
    p = int(round(period))
    salience = float(ac[max(1, p - 1):p + 2].max()) if p + 2 <= len(ac) else 0.0
    win, hop = int(12 * fps), int(6 * fps)
    lo, hi = int(fps * 60 / 200), int(fps * 60 / 55)
    ok = tot = 0
    for a in range(0, max(1, len(env) - win), hop):
        w = env[a:a + win] - env[a:a + win].mean()
        if len(w) < hi + 2 or np.abs(w).sum() < 1e-6:
            continue
        c = np.correlate(w, w, mode='full')[len(w) - 1:]
        c = c / (c[0] + 1e-12)
        k = lo + int(np.argmax(c[lo:hi]))
        tot += 1
        rel = k / period
        if c[k] > 0.05 and any(abs(rel - m) <= 0.05 * m for m in (0.5, 1.0, 2.0)):
            ok += 1
    return salience, (ok / tot if tot else 0.0)


def _refine(y, sr, times, search=0.035, prior=0.02, min_rise_db=6.0):
    """Each time moved to the sharpest energy rise (5 ms over 4 ms windows) within `search`, weighted toward the
    original; kept where there is no clear transient. Returns (times, how many moved)."""
    hop = max(1, int(sr * 0.001))
    w = max(2, int(sr * 0.004))
    lag = max(1, int(round(0.005 * sr / hop)))
    c = np.concatenate([[0.0], np.cumsum(np.asarray(y, np.float64) ** 2)])
    out, moved = [], 0
    for t in times:
        a, b = int((t - search - 0.012) * sr), int((t + search + 0.012) * sr)
        if a < 0 or b + w >= len(y):
            out.append(float(t))
            continue
        pos = np.arange(a, b, hop)
        le = 10 * np.log10((c[pos + w] - c[pos]) / w + 1e-10)
        rise = le[lag:] - le[:-lag]
        tt = (pos[lag:] + w / 2) / sr - 0.002
        inside = np.abs(tt - t) <= search
        if not inside.any():
            out.append(float(t))
            continue
        score = np.where(inside, rise * np.exp(-0.5 * ((tt - t) / prior) ** 2), -1e9)
        k = int(np.argmax(score))
        if rise[k] >= min_rise_db:
            out.append(float(tt[k]))
            moved += abs(tt[k] - t) > 0.002
        else:
            out.append(float(t))
    out = np.maximum.accumulate(np.asarray(out))       # never out of order
    return out.tolist(), int(moved)


def _downbeat_phase(beats, chroma, mel, fps, bpb):
    """(phase, margin): the beat (0..bpb-1) bars start on, from chord changes (chroma across the beat) and the low
    bands' rise; margin = (best - second best) phase score, in standard deviations."""
    nb = len(beats)
    if nb < 2 * bpb + 2:
        return 0, 0.0
    fr = np.clip(np.round(np.asarray(beats) * fps).astype(int), 0, len(chroma) - 1)
    seg = []
    for i in range(nb - 1):
        a, b = fr[i], max(fr[i] + 1, fr[i + 1])
        v = chroma[a:b].mean(0)
        seg.append(v / (np.linalg.norm(v) + 1e-9))
    seg = np.array(seg)
    change = np.zeros(nb)
    change[1:nb - 1] = 1 - np.sum(seg[:-1] * seg[1:], axis=1)
    low = mel[:, :4].mean(1)
    rise = np.zeros(nb)
    for i in range(nb):
        f = fr[i]
        rise[i] = low[f:f + 3].mean() - low[max(0, f - 3):max(1, f)].mean() if f >= 1 else 0.0

    def z(x):
        return (x - x.mean()) / (x.std() + 1e-9)
    s = z(change) + 0.5 * z(rise)
    scores = np.array([s[p::bpb].mean() for p in range(bpb)])
    order = np.argsort(scores)[::-1]
    return int(order[0]), float(scores[order[0]] - scores[order[1]])


def _novelty(F, w=4):
    """Checkerboard novelty at each bar boundary (0..J) of a bar-feature matrix (rows normalized)."""
    J = len(F)
    S = F @ F.T
    nov = np.zeros(J + 1)
    for j in range(1, J):
        k = min(w, j, J - j)
        a, b = S[j - k:j, j - k:j], S[j:j + k, j:j + k]
        x = S[j - k:j, j:j + k]
        nov[j] = (a.mean() + b.mean()) / 2 - x.mean()
    if nov.max() > nov.min():
        nov = (nov - nov.min()) / (nov.max() - nov.min())
    return nov


def _norm01(x, lo_pct=5, hi_pct=95):
    x = np.asarray(x, float)
    lo, hi = np.percentile(x, lo_pct), np.percentile(x, hi_pct)
    if hi - lo < 1e-9:
        return np.full_like(x, 0.5)
    return np.clip((x - lo) / (hi - lo), 0.0, 1.0)


def analyze(song, beats_per_bar=4, refresh=False):
    """The song's structure for scoring (cached by file content and analysis version). Keys: duration, bpm, beat_s,
    bar_s, beat_quality ('clear' | 'weak' | 'none'), clarity {stability, salience, tracker_pulse}, coarse (no steady
    beat: bars are coarse units), beats (refined times), downbeat_phase, bars [[start, end], ...], bar_beats, energy
    (0-1 per bar), loud_db, density, timbre / chroma (per bar), novelty (per bar line), phrases (bar indices),
    phrase_offset, drops [{bar, jump_db}], ending {natural, bars (candidate first bars of an ending)}, sections (energy
    sections), integrated_lufs, peak_dbfs, notes."""
    import letitedit.footage.perception as perception
    import letitedit.sound.audio_library as audio_library
    song = str(audio_library.song_file(str(song)))
    if not Path(song).is_file():
        raise FileNotFoundError(f'No song at {song}')
    # the shared content key (size + the first 2 MB) is the same for a song changed past its first 2 MB, so the
    # file's modification time is part of this key, and a fresh analysis refreshes the shared beat cache too
    key = (f'{perception.content_key(song)}-{os.stat(song).st_mtime_ns % 10 ** 12}-b{int(beats_per_bar)}'
           f'-v{ANALYSIS_VERSION}')
    f = WORK / 'songs' / f'{key}.json'
    with _LOCK:
        if not refresh and key in _MEM:
            return _MEM[key]
    if f.exists() and not refresh:
        try:
            with open(f, encoding='utf-8-sig') as fh:
                an = json.load(fh)
            an['path'] = song
            with _LOCK:
                _MEM[key] = an
            return an
        except ValueError:
            pass
    an = _analyze(song, int(beats_per_bar))
    an['key'] = key
    _json_write(f, an)
    with _LOCK:
        _MEM[key] = an
    return an


def _analysis_bar_grid(L, an, bpb, bt, chroma, env, fps, mel, notes, period_s, pm, quality, salience,
        stability, y):
    if quality != 'none':
        beats, moved = _refine(y, SR, bt.tolist())
        an['beats_refined'] = moved
        phase, margin = _downbeat_phase(beats, chroma, mel, fps, bpb)
        beat_down = np.asarray(pm.get('downbeats') or [], float)      # the beat finder's bars, when its bar length is this one
        if beat_down.size and int(pm.get('beats_per_bar') or bpb) == int(bpb):
            phase = int(np.argmin(np.abs(np.asarray(beats, float) - beat_down[0]))) % bpb
        tracker_down = np.asarray(pm.get('downbeats') or [], float)
        tracker_phase = None
        if tracker_down.size:
            tracker_phase = int(np.argmin(np.abs(bt - tracker_down[0]))) % bpb
        an['downbeat_phase'] = {'beat': phase, 'margin': round(margin, 2), 'tracker_beat': tracker_phase,
                                'from': 'chord changes + low-band rise'}
        if tracker_phase is not None and tracker_phase != phase:
            notes.append(f'bars start on tracked beat {phase} (chord changes), not {tracker_phase} (the beat finder\'s '
                         f'loudest beat); margin {margin:.2f}')
        if margin < 0.3:
            notes.append(f'the downbeat is uncertain (phase margin {margin:.2f}): "downbeat" hits may land on beat 3')
        beat_s = float(np.median(np.diff(beats)))
        down_idx = list(range(phase, len(beats) - bpb + 1, bpb))
        bars, bar_beats = [], []
        for i in down_idx:
            if i + bpb < len(beats):
                end = beats[i + bpb]
            else:
                end = min(L, beats[i] + bpb * beat_s)
            if end - beats[i] < 0.5 * bpb * beat_s:
                break
            bars.append([float(beats[i]), float(end)])
            bar_beats.append([float(b) for b in beats[i:i + bpb]])
        an['beats'] = [round(b, 4) for b in beats]
        an['bpm'] = round(60.0 / beat_s, 2)
        an['beat_s'] = round(beat_s, 5)
    else:
        # no steady beat: coarse units of about 2 s (or a bar of the beat finder's tempo), snapped to strong onsets
        unit = 2.0
        if period_s and 1.5 <= bpb * period_s <= 4.0:
            unit = bpb * period_s
        first = float(np.flatnonzero(env > env.mean())[0] / fps) if np.any(env > env.mean()) else 0.0
        grid = np.arange(first, L - 0.5 * unit, unit)
        snapped = []
        for g in grid:
            lo, hi = int((g - 0.2 * unit) * fps), int((g + 0.2 * unit) * fps)
            lo, hi = max(0, lo), min(len(env), max(lo + 1, hi))
            k = lo + int(np.argmax(env[lo:hi]))
            t = k * HOP / SR + 1024 / SR
            if snapped and t <= snapped[-1] + 0.5 * unit:
                t = g
            snapped.append(float(t))
        bars = [[a, b] for a, b in zip(snapped, snapped[1:] + [min(L, snapped[-1] + unit)]) if b - a > 0.3 * unit]
        bar_beats = [[a] for a, _ in bars]
        an['beats'] = []
        an['bpm'] = round(60.0 / period_s, 2) if period_s else None
        an['beat_s'] = round(unit / bpb, 5)
        an['downbeat_phase'] = None
        notes.append(f'no steady beat (stability {stability:.2f}, salience {salience:.2f}): the song is cut in '
                     f'{unit:.1f} s units snapped to its strongest onsets, joined with long crossfades; hit times are '
                     'approximate')
    return bars, bar_beats


def _analysis_bar_features(J, an, bar_beats, bars, chroma, env, fps, mel, notes, y):
    # per-bar features
    loud, dens, timbre, chrom, entry_ch, exit_ch = [], [], [], [], [], []
    for (a, b), bb in zip(bars, bar_beats):
        i0, i1 = int(a * SR), max(int(a * SR) + 1, int(b * SR))
        loud.append(10 * math.log10(float(np.mean(y[i0:i1] ** 2)) + 1e-10))
        f0, f1 = int(round(a * fps)), max(int(round(a * fps)) + 1, int(round(b * fps)))
        f1 = min(f1, len(mel))
        f0 = min(f0, f1 - 1)
        dens.append(float(env[f0:f1].mean()) if f1 > f0 else 0.0)
        timbre.append(mel[f0:f1].mean(0))
        c = chroma[f0:f1].mean(0)
        chrom.append(c / (np.linalg.norm(c) + 1e-9))
        q = max(1, (f1 - f0) // max(1, len(bb)))
        ce, cx = chroma[f0:f0 + q].mean(0), chroma[max(f0, f1 - q):f1].mean(0)
        entry_ch.append(ce / (np.linalg.norm(ce) + 1e-9))
        exit_ch.append(cx / (np.linalg.norm(cx) + 1e-9))
    loud, dens = np.asarray(loud), np.asarray(dens)
    timbre = np.asarray(timbre)
    tz = (timbre - timbre.mean(0)) / (timbre.std(0) + 1e-6)
    # material for anywhere in an arrangement: not near-silence, not inside a fade-out (those bars stay available to
    # the song's own ending); energy is scaled on that material, so a quiet "low" bar is music, not a fade
    starts0 = np.asarray([b[0] for b in bars])
    usable = loud >= float(np.percentile(loud, 95)) - 25.0
    fade_from = None
    if an['sections'] and str(an['sections'][-1][2]).startswith('outro (fades'):
        fade_from = float(an['sections'][-1][0])
    elif J >= 8:
        k = J - 1
        while k > 0 and loud[k] < loud[k - 1] - 0.5:
            k -= 1
        if J - k >= 3 and loud[k] - loud[J - 1] > 10:
            fade_from = float(bars[k][0])
    if fade_from is not None:
        usable &= starts0 < fade_from - 1e-6
        notes.append(f'the song fades out from {_clock(fade_from)}: those bars are kept for its own ending only')
    if usable.sum() < 4:
        usable[:] = True
    ref = usable if usable.sum() >= 4 else np.ones(J, bool)

    def scaled(x):
        lo, hi = np.percentile(x[ref], 5), np.percentile(x[ref], 95)
        return np.full_like(x, 0.5) if hi - lo < 1e-9 else np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    energy = 0.75 * scaled(loud) + 0.25 * scaled(dens)
    an['usable'] = [bool(x) for x in usable]
    an['loud_db'] = [round(float(x), 2) for x in loud]
    an['density'] = [round(float(x), 3) for x in dens]
    an['energy'] = [round(float(x), 3) for x in energy]
    an['timbre'] = [[round(float(v), 3) for v in row] for row in tz]
    an['chroma'] = [[round(float(v), 4) for v in row] for row in chrom]
    an['entry_chroma'] = [[round(float(v), 4) for v in row] for row in entry_ch]
    an['exit_chroma'] = [[round(float(v), 4) for v in row] for row in exit_ch]
    return loud, energy, tz, chrom


def _analysis_phrases_and_drops(J, an, bars, chrom, energy, loud, notes, tz):
    # phrases: a 4-bar grid fitted to the novelty, plus energy-section starts and strong novelty peaks
    F = np.hstack([tz / math.sqrt(tz.shape[1]), 0.8 * np.asarray(chrom)])
    F = F / (np.linalg.norm(F, axis=1, keepdims=True) + 1e-9)
    nov = _novelty(F, 4)
    an['novelty'] = [round(float(x), 3) for x in nov]
    plen = 4
    offs = [float(np.mean(nov[1:J][((np.arange(1, J) - o) % plen) == 0])) if J > plen else 0.0 for o in range(plen)]
    off = int(np.argmax(offs))
    starts = np.asarray([b[0] for b in bars])
    phrases = {j for j in range(J) if (j - off) % plen == 0}
    for s in an['sections']:
        j = int(np.argmin(np.abs(starts - float(s[0]))))
        if abs(starts[j] - float(s[0])) <= 2.0:
            phrases.add(j)
    if J > 8:
        thr = float(np.percentile(nov[1:J], 85))
        phrases |= {j for j in range(1, J) if nov[j] >= thr and nov[j] > 0.3}
    phrases.add(0)
    an['phrases'] = sorted(phrases)
    an['phrase_offset'] = off
    an['phrase_bars'] = plen
    # drops: the next two bars 3 dB+ louder than the two before, into a loud stretch; ranked by that jump, the
    # rise of the next four bars over the four before, and a start on the 4-bar phrase grid
    drops = []
    for j in range(2, J - 1):
        jump = float(np.mean(loud[j:j + 2]) - np.mean(loud[j - 2:j]))
        after = float(np.mean(energy[j:j + 4]))
        before = float(np.mean(energy[max(0, j - 4):j]))
        if jump >= 3.0 and after >= 0.7:
            on_grid = (j - off) % plen == 0
            drops.append({'bar': j, 'jump_db': round(jump, 2), 'energy_after': round(after, 3),
                          'phrase': j in phrases,
                          'score': round(jump + 4.0 * (after - before) + (1.5 if on_grid else 0.0), 2)})
    drops.sort(key=lambda d: -d['score'])
    kept = []                                           # the strongest of each neighbourhood
    for d in drops:
        if all(abs(d['bar'] - k['bar']) > 2 for k in kept):
            kept.append(d)
    an['drops'] = kept[:10]
    if not kept:
        best = None
        for j in range(2, J - 1):
            jump = float(np.mean(loud[j:j + 2]) - np.mean(loud[j - 2:j]))
            if best is None or jump > best['jump_db']:
                best = {'bar': j, 'jump_db': round(jump, 2), 'energy_after': round(float(np.mean(energy[j:j + 4])), 3),
                        'phrase': j in phrases}
        an['drops_weak'] = [best] if best else []
        notes.append('no clear drop (no bar line where the music gets 3 dB+ louder into a loud stretch); a "drop" '
                     f'hit uses the biggest rise (+{best["jump_db"]:.1f} dB at {_clock(bars[best["bar"]][0])})'
                     if best else 'no drop candidates')
    return phrases


def _analyze(song, bpb):
    import letitedit.footage.perception as perception
    pm = perception.music(song, refresh=True)
    y = perception._decode_audio(song, SR)
    L = len(y) / SR
    notes = []
    an = {'v': ANALYSIS_VERSION, 'path': song, 'duration': round(L, 3), 'beats_per_bar': bpb,
          'tracker': {'bpm': pm.get('bpm'), 'pulse': pm.get('pulse'), 'beats': pm.get('beats')},
          'sections': pm.get('sections') or []}
    try:
        import letitedit.sound.music as music
        an['integrated_lufs'] = float(music.loudness(song))
    except Exception:  # noqa: BLE001 - level matching then uses the bars' own loudness
        an['integrated_lufs'] = None
    y2 = _decode(song, MSR, 2)
    an['peak_dbfs'] = round(20 * math.log10(float(np.abs(y2).max(initial=1e-9)) + 1e-12), 2) if len(y2) else -120.0
    del y2
    if L < 4 or float(np.abs(y).max(initial=0)) < 1e-4:
        raise ValueError(f'{song}: too short or silent to score with ({L:.1f} s)')
    mel, chroma = _frame_features(y)
    fps = SR / HOP
    beats_mod = perception._beats_module()
    env = beats_mod.onset_envelope(y, SR)
    bt = np.asarray(pm.get('beat_times') or [], float)
    if pm.get('bpm') and len(bt) >= 8:
        period_s = float(np.median(np.diff(bt)))
        salience, stability = _clarity(env, fps, period_s * fps)
    else:
        period_s, salience, stability = None, 0.0, 0.0
    an['clarity'] = {'stability': round(stability, 3), 'salience': round(salience, 3),
                     'tracker_pulse': pm.get('pulse'),
                     'about': 'stability: share of 12 s windows whose own tempo agrees with the song\'s; salience: '
                              'onset autocorrelation at the beat period; both measured, neither a probability'}
    if period_s and stability >= 0.6 and salience >= 0.12:
        quality = 'clear'
    elif period_s and (stability >= 0.3 or salience >= 0.12):
        quality = 'weak'
    else:
        quality = 'none'
    if pm.get('beat_finder_error'):
        notes.append(f"The beat finder couldn't run, so this song has no beats here: {pm['beat_finder_error']}")
        an['beat_finder_error'] = pm['beat_finder_error']
    an['beat_quality'] = quality
    an['coarse'] = quality == 'none'
    bars, bar_beats = _analysis_bar_grid(L, an, bpb, bt, chroma, env, fps, mel, notes, period_s, pm, quality,
        salience, stability, y)
    if len(bars) < 4:
        raise ValueError(f'{song}: found only {len(bars)} bars; too short to arrange')
    J = len(bars)
    bars_a = np.asarray(bars)
    an['bars'] = [[round(a, 4), round(b, 4)] for a, b in bars]
    an['bar_beats'] = [[round(b, 4) for b in bb] for bb in bar_beats]
    an['bar_s'] = round(float(np.median(bars_a[:, 1] - bars_a[:, 0])), 5)
    loud, energy, tz, chrom = _analysis_bar_features(J, an, bar_beats, bars, chroma, env, fps, mel, notes, y)
    phrases = _analysis_phrases_and_drops(J, an, bars, chrom, energy, loud, notes, tz)
    # ending: does the song end by itself (a fade or a final chord), and where could an ending start
    tail = y[max(0, int((L - 3.0) * SR)):]
    tail_db = 10 * math.log10(float(np.mean(tail[-int(0.5 * SR):] ** 2)) + 1e-10) if len(tail) > SR else -100.0
    natural = bool((an['sections'] and str(an['sections'][-1][2]).startswith('outro')) or
                   tail_db < float(np.median(loud)) - 12)
    ends = [j for j in sorted(phrases, reverse=True) if 4.0 <= L - bars[j][0] <= 45.0]
    if not ends:
        ends = [j for j in range(J - 1, -1, -1) if L - bars[j][0] >= 4.0][:1]
    an['ending'] = {'natural': natural, 'bars': ends[:6], 'tail_db': round(tail_db, 1)}
    an['notes'] = notes
    return an


def song_brief(an):
    """What the AI needs to choose hits and sections: tempo, clarity, sections, phrases, drops, ending."""
    bars = an['bars']

    def at(j):
        return _clock(bars[j][0])
    out = {'song': an['path'], 'duration_s': an['duration'], 'bpm': an.get('bpm'), 'beat_quality': an['beat_quality'],
           'clarity': an['clarity'], 'coarse': an['coarse'], 'bars': len(bars), 'bar_s': an['bar_s'],
           'integrated_lufs': an.get('integrated_lufs'), 'peak_dbfs': an.get('peak_dbfs'),
           'energy_sections': [f'{_span(a, b)} {name} ({rel:+.0f} dB)' for a, b, name, rel in an.get('sections') or []],
           'phrase_starts': [at(j) for j in an['phrases']][:48],
           'drops': [f"{at(d['bar'])} bar {d['bar'] + 1} (+{d['jump_db']:.1f} dB)" for d in an.get('drops') or []],
           'ending': {'natural': an['ending']['natural'], 'starts': [at(j) for j in an['ending']['bars']]},
           'energy_by_bar': ' '.join(str(int(round(9 * e))) for e in an['energy']),
           'notes': an.get('notes') or []}
    if an.get('downbeat_phase'):
        out['downbeat_phase'] = an['downbeat_phase']
    return out
