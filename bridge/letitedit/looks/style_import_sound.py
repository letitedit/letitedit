"""Sound for style_import: speech, loudness, music (tempo, beats, cuts on beats, level under speech and in the gaps),
sound effects (sharp onsets in the music-and-effects stem away from the beat, sorted by what they sound like with
CLAP), clicks tied to cuts and to words (sound_sync) and silences.

GPU models (Whisper for the words, Demucs for the stems, CLAP for the sound kinds) take the server's GPU turn; before
each, wait_for_renders() waits while someone else holds the PC render lock (the PC power-crashed under a render plus
a GPU model). Everything else is CPU.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import math
import os
import subprocess
import time
from pathlib import Path

import numpy as np

SR = 22050
HOP = 256                      # 11.6 ms
SFX_LABELS = ['a whoosh', 'a swoosh', 'a pop sound effect', 'a ding', 'a bell chime', 'a cash register', 'a boom',
              'a deep bass hit', 'an impact', 'a click', 'a camera shutter', 'a record scratch', 'a glitch sound',
              'a riser', 'a notification sound', 'a cartoon boing', 'a laugh track', 'applause', 'a beep',
              'a typing sound', 'a slide whistle', 'a drum hit']
NOT_SFX = ['music', 'a man speaking', 'a woman speaking', 'silence', 'room noise', 'singing']
SFX_GROUP = {'a whoosh': 'whoosh', 'a swoosh': 'whoosh', 'a riser': 'riser', 'a pop sound effect': 'pop',
             'a cartoon boing': 'pop', 'a ding': 'ding', 'a bell chime': 'ding', 'a notification sound': 'ding',
             'a beep': 'ding', 'a cash register': 'ding', 'a boom': 'boom / bass hit', 'a deep bass hit': 'boom / bass hit',
             'an impact': 'boom / bass hit', 'a drum hit': 'boom / bass hit', 'a click': 'click',
             'a camera shutter': 'click', 'a typing sound': 'click', 'a record scratch': 'scratch / glitch',
             'a glitch sound': 'scratch / glitch', 'a laugh track': 'laugh / applause', 'applause': 'laugh / applause',
             'a slide whistle': 'whistle'}


def energy_profile(envelope, hop_s, bin_s=1.0, drop_db=6.0):
    """Median RMS envelope in fixed bins and sustained two-bin level drops, not musical semantics."""
    if not math.isfinite(hop_s) or not math.isfinite(bin_s) or hop_s <= 0 or bin_s <= 0:
        raise ValueError('hop_s and bin_s must be positive and finite')
    if not math.isfinite(drop_db) or drop_db <= 0:
        raise ValueError('drop_db must be positive and finite')
    envelope = np.asarray(envelope, dtype=float)
    if envelope.ndim != 1:
        raise ValueError('envelope must be one-dimensional')
    duration = len(envelope) * hop_s
    curve = []
    for index in range(int(math.ceil(duration / bin_s))):
        start, end = index * bin_s, min(duration, (index + 1) * bin_s)
        values = envelope[int(round(start / hop_s)):int(round(end / hop_s))]
        values = values[np.isfinite(values)]
        curve.append({'t': round(start, 3), 'end': round(end, 3),
                      'rms_dbfs': round(float(np.median(values)), 2) if len(values) else None})
    drops = []
    covered_until = -1.0
    for index in range(2, len(curve) - 1):
        context = curve[index - 2:index + 2]
        if any(row['rms_dbfs'] is None or row['end'] - row['t'] < bin_s * 0.9 for row in context):
            continue
        before = [row['rms_dbfs'] for row in context[:2]]
        after = [row['rms_dbfs'] for row in context[2:]]
        level = float(np.median(before))
        at = curve[index]['t']
        if at < covered_until or level < -45 or max(before) - min(before) > 3 or level - max(after) < drop_db:
            continue
        recovery = next((row['t'] for row in curve[index + 2:]
                         if row['rms_dbfs'] is not None and row['rms_dbfs'] >= level - 3), duration)
        drops.append({'t': at, 'end': round(recovery, 3),
                      'drop_db': round(level - float(np.median(after)), 2)})
        covered_until = recovery
    return {'bin_s': bin_s, 'curve': curve, 'drops': drops,
            'method': f'median RMS envelope per bin in dBFS; drop = at least two bins {drop_db:g} dB below two stable active '
                      'bins; not LUFS, a beat drop, instrument identity or an inferred production effect'}


def wait_for_renders(max_wait_s=1800, poll_s=15, log=None, check=None):
    """Wait while another process holds the PC render lock (no GPU model while a render runs). Returns the seconds
    waited; after max_wait_s it returns anyway with a note in the log."""
    import letitedit.core.render_lock as render_lock
    t0 = time.monotonic()
    said = False
    while True:
        try:
            i = render_lock.info()
        except Exception:  # noqa: BLE001
            return 0.0
        mine = i.get('owner_pid') in set(render_lock.ancestors()) if i.get('owner_pid') else False
        if not i.get('held') or i.get('stale') or not i.get('owner_alive', True) or mine:
            return round(time.monotonic() - t0, 1)
        if not said and log:
            log(f'waiting for the render to finish before a GPU model: {i.get("text")}')
            said = True
        if time.monotonic() - t0 > max_wait_s:
            if log:
                log(f'the render lock was still held after {max_wait_s} s; going on')
            return round(time.monotonic() - t0, 1)
        if check:
            check()
        time.sleep(poll_s)


def decode_audio(path, sr=SR, start=None, duration=None):
    import letitedit.timeline.made as made
    args = [str(made.ffmpeg_exe()), '-v', 'error', '-nostdin']
    if start:
        args += ['-ss', f'{start:.3f}']
    args += ['-i', str(path)]
    if duration:
        args += ['-t', f'{duration:.3f}']
    args += ['-vn', '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-']
    r = subprocess.run(args, capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                       stdin=subprocess.DEVNULL)
    return np.frombuffer(r.stdout, np.float32).copy()


def envelope_db(y, sr=SR, hop=HOP, win=1024):
    """RMS level in dBFS every hop samples."""
    if len(y) < win:
        return np.full(1, -120.0)
    n = 1 + (len(y) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    rms = np.sqrt(np.mean(y[idx] ** 2, axis=1) + 1e-12)
    return 20 * np.log10(rms + 1e-9)


def spectral_flux(y, sr=SR, hop=HOP, win=1024):
    """Onset strength: half-wave rectified rise of the log spectrum, summed over bins, every hop."""
    if len(y) < win:
        return np.zeros(1)
    n = 1 + (len(y) - win) // hop
    w = np.hanning(win).astype(np.float32)
    frames = np.lib.stride_tricks.as_strided(y, shape=(n, win), strides=(y.strides[0] * hop, y.strides[0]))
    spec = np.abs(np.fft.rfft(frames * w, axis=1))
    logs = np.log1p(100 * spec)
    flux = np.maximum(0.0, np.diff(logs, axis=0)).sum(axis=1)
    return np.r_[0.0, flux]


def onsets(flux, hop_s, z=3.0, min_gap_s=0.12, win_s=1.5):
    """Peaks of the onset strength over a moving median + z * a moving spread (MAD): [(t, strength z)]."""
    from scipy.ndimage import median_filter
    k = max(3, int(win_s / hop_s) | 1)
    med = median_filter(flux, size=k, mode='nearest')
    mad = median_filter(np.abs(flux - med), size=k, mode='nearest') + 1e-6
    zz = (flux - med) / (1.4826 * mad)
    out = []
    gap = int(min_gap_s / hop_s)
    i = 1
    while i < len(zz) - 1:
        if zz[i] >= z and zz[i] >= zz[i - 1] and zz[i] >= zz[i + 1]:
            j = min(len(zz), i + gap)
            k2 = i + int(np.argmax(zz[i:j]))
            out.append((k2 * hop_s, float(zz[k2])))
            i = k2 + gap
        else:
            i += 1
    return out


def speech_spans(words, join_s=0.3):
    spans = []
    for w in words:
        s, e = float(w['s']), float(w.get('e', w['s']))
        if spans and s - spans[-1][1] < join_s:
            spans[-1][1] = max(spans[-1][1], e)
        else:
            spans.append([s, e])
    return spans


def level_in(env_db, hop_s, spans, invert=False, duration=None, min_len=0.0):
    """Median dB of env over the spans (or outside them with invert), using only stretches of at least min_len."""
    n = len(env_db)
    mask = np.zeros(n, bool)
    for a, b in spans:
        if b - a < min_len and not invert:
            continue
        mask[max(0, int(a / hop_s)):min(n, int(math.ceil(b / hop_s)))] = True
    if invert:
        mask = ~mask
        if min_len > 0:
            # keep only gaps of min_len and more
            keep = np.zeros(n, bool)
            i = 0
            while i < n:
                if not mask[i]:
                    i += 1
                    continue
                j = i
                while j < n and mask[j]:
                    j += 1
                if (j - i) * hop_s >= min_len:
                    keep[i:j] = True
                i = j
            mask = keep
    vals = env_db[mask]
    vals = vals[vals > -90]
    return (round(float(np.median(vals)), 1), round(float(mask.sum() * hop_s), 1)) if len(vals) else (None, 0.0)


def _measure_loudness(checks, video, out, dur, prog):
    """Measure loudness and interior quiet stretches, retaining partial errors."""
    # loudness (EBU R128, 0.1 s steps)
    try:
        series, summ = checks.loudness_series(str(video))
        out['loudness'] = {k: summ.get(k) for k in ('integrated_lufs', 'range_lu', 'true_peak_dbfs')}
        mom = np.array([m if m is not None else -120 for _, m, _ in series], np.float32)
        quiet = []
        i = 0
        while i < len(mom):
            if mom[i] > -45:
                i += 1
                continue
            j = i
            while j < len(mom) and mom[j] <= -45:
                j += 1
            if (j - i) * 0.1 >= 0.3 and 0.2 < i * 0.1 < dur - 0.5:
                quiet.append({'t': round(i * 0.1, 2), 'len': round((j - i) * 0.1, 2)})
            i = j
        out['silences'] = {'count': len(quiet), 'stretches': quiet[:20],
                           'what': 'momentary loudness under -45 LUFS for 0.3 s or more (not counting the very start and end)'}
    except Exception as e:  # noqa: BLE001
        out['loudness'] = {'error': f'{type(e).__name__}: {e}'[:300]}
    prog(0.25, 'loudness')


def _measure_music(log, check, video, separate, prog, env_mus, hop_s, spans, out, env_voc, env_mix, cuts):
    """Measure beats, music levels and their relation to speech and cuts."""
    # music: the server's music lane (the beat finder; separated when someone talks)
    music = {}
    try:
        wait_for_renders(log=log, check=check)
        import letitedit.timing.music_sync as music_sync
        lane = music_sync.music(str(video), settings={'stem': 'auto' if separate else 'mix'})
        beats = [b['t'] for b in lane.get('beats') or [] if b.get('audible', True)]
        music = {'tempo_bpm': lane.get('tempo_bpm'), 'beat_quality': lane.get('beat_quality'),
                 'beat_confidence': lane.get('beat_confidence'), 'tracker': lane.get('tracker'),
                 'beats': len(beats), 'beat_times': [round(b, 3) for b in beats[:3000]], 'stem': lane.get('stem'),
                 'music_spans': lane.get('music_spans')}
    except Exception as e:  # noqa: BLE001
        beats = []
        music = {'error': f'{type(e).__name__}: {e}'[:300]}
    prog(0.6, 'music')
    # how much of the video has music: the music stem over -45 dBFS (or the mix when not separated)
    if env_mus is not None:
        music['energy'] = energy_profile(env_mus, hop_s)
        music['energy']['source'] = 'separated music-and-effects stem; may contain non-music sounds'
        on = env_mus > -45
        music['music_share'] = round(float(on.mean()), 3)
        if spans and (out['speech'].get('speech_share') or 0) >= 0.15:
            under, s_len = level_in(env_mus, hop_s, spans)
            gap_level, g_len = level_in(env_mus, hop_s, spans, invert=True, min_len=0.5)
            voice, _ = level_in(env_voc, hop_s, spans) if env_voc is not None else (None, 0)
            music['level_under_speech_db'] = under
            music['level_in_gaps_db'] = gap_level
            music['gaps_measured_s'] = g_len
            if under is not None and gap_level is not None:
                music['ducking_db'] = round(gap_level - under, 1)
            if under is not None and voice is not None:
                music['under_voice_db'] = round(under - voice, 1)
        music['level_note'] = ('RMS of the separated music stem (Demucs) in dBFS: under speech = while words are '
                               'said, gaps = pauses of 0.5 s and more; ducking = gap level minus level under speech')
    else:
        music['energy'] = {'available': False, 'why': 'music was not separated from speech and effects'}
    out['mix_energy'] = energy_profile(env_mix, hop_s)
    out['mix_energy']['source'] = 'whole soundtrack, including speech and effects; not music-only energy'
    # cuts on the beat
    if beats and cuts:
        bt = np.array(sorted(beats))
        d = [float(np.min(np.abs(bt - c['t']))) for c in cuts]
        ibi = float(np.median(np.diff(bt))) if len(bt) > 2 else 0.5
        on_beat = sum(1 for x in d if x <= 0.07)
        music['cuts_on_beat'] = {'share': round(on_beat / len(d), 3), 'chance': round(min(1.0, 0.14 / ibi), 3),
                                 'within_s': 0.07, 'cuts': len(d),
                                 'median_offset_s': round(float(np.median(d)), 3)}
    out['music'] = music
    return music, beats


def _measure_effects(stems, dur, cuts, flashes, picture_events, info, out, mus, mix, env_mus, env_mix, beats, music, spans, hop_s, log, check, prog, classify, video, overlays, words):
    """Measure and classify sound effects, using residue evidence when available."""
    # sound effects (T198): with the stems, from what is left after speech and music (residue_sfx); the sharp-onset
    # rule below stays for a video that could not be separated
    residue = None
    if stems and RESIDUE_ON:
        try:
            residue = residue_sfx(stems['files'], duration=dur, cuts=[c['t'] if isinstance(c, dict) else c for c in cuts],
                                  picture_events=list(flashes) if picture_events is None else picture_events,
                                  fps=info.get('fps') or 30.0)
        except Exception as e:  # noqa: BLE001
            out['sfx_residue_error'] = f'{type(e).__name__}: {e}'[:300]
    # without stems: sharp onsets in the music-and-effects stem (or the mix without speech) away from the beat
    sfx = []
    src = mus if mus is not None else mix
    flux = spectral_flux(src)
    cands = onsets(flux, hop_s, z=3.0 if mus is not None else 4.0)
    env_src = env_mus if env_mus is not None else env_mix
    bt = np.array(sorted(beats)) if beats else None
    for t, z in cands:
        if t < 0.05 or t > dur - 0.1:
            continue
        k = int(t / hop_s)
        lvl = float(env_src[min(len(env_src) - 1, k + 3)]) if len(env_src) else -120
        if lvl < -42:
            continue
        on_beat = bool(bt is not None and len(bt) and float(np.min(np.abs(bt - t))) < 0.045
                       and (music.get('beat_quality') in ('clear', 'weak')))
        if mus is None:
            # no stems: skip onsets inside speech (syllables)
            if any(a - 0.05 <= t <= b + 0.05 for a, b in spans):
                continue
        before = env_src[max(0, k - int(1.0 / hop_s)):max(1, k - int(0.05 / hop_s))]
        after = env_src[k:k + int(0.15 / hop_s)]
        jump = float(np.max(after) - np.median(before)) if len(before) and len(after) else 0.0
        sfx.append({'t': round(t, 3), 'strength': round(z, 1), 'level_db': round(lvl, 1), 'on_beat': on_beat,
                    'jump_db': round(jump, 1)})
    # which candidates are effects: with the music-and-effects stem, a moment that sounds unlike the music around it
    # (CLAP embedding novelty) and jumps 10 dB or more over the second before; without stems, the strongest onsets
    # off the beat (the earlier rule)
    novel = None
    # (only with music that has a beat: without music the stem holds the footage's own sounds, a tool's click or a
    # door, which are just as sharp and unlike their surroundings)
    # (a beat is required: with the stem merely sounding most of the time, real sounds in the footage, a hammer, a
    # door, were taken for effects: 16 false on one Short, measured 30 Oct)
    if sfx and stems and music.get('beat_quality') in ('clear', 'weak') and residue is None:
        try:
            wait_for_renders(log=log, check=check)
            novel = novelty(stems['files']['music'], [s['t'] for s in sfx])
        except Exception as e:  # noqa: BLE001
            out['sfx_novelty_error'] = f'{type(e).__name__}: {e}'[:300]
    if sfx and novel is not None:
        for s, nv in zip(sfx, novel):
            s['novelty'] = round(nv, 3)
        sfx = [dict(s, by='novelty') for s in sfx if s['novelty'] >= SFX_RULE['novelty']
               and s['jump_db'] >= SFX_RULE['jump_db']]
    elif sfx:
        zs = np.array([s['strength'] for s in sfx])
        cut_z = max(4.0, float(np.percentile(zs, 50)))
        sfx = [s for s in sfx if (not s['on_beat'] and s['strength'] >= cut_z) or s['strength'] >= 2 * cut_z]
    prog(0.7, 'sound effects')
    if classify and sfx and residue is None:
        try:
            wait_for_renders(log=log, check=check)
            sfx = classify_sfx(video, sfx, stems)
        except Exception as e:  # noqa: BLE001
            out['sfx_classify_error'] = f'{type(e).__name__}: {e}'[:300]
    for w in whooshes(src, [c['t'] for c in cuts]):
        if not any(abs(w['t'] - x['t']) < 0.25 for x in sfx):
            sfx.append(w)
    sfx.sort(key=lambda x: x['t'])
    for s in sfx:
        # found by novelty: the kind model often calls a real effect under music 'music'; it stays, unsorted
        if s.get('by') == 'novelty' and s.get('kind') in ('music', 'speech'):
            s['kind_heard'] = s['kind']
            s['kind'] = 'unsorted'
    keep = [s for s in sfx if s.get('kind') not in ('music', 'speech')]
    cut_t = [c['t'] for c in cuts]
    ov_t = [o['t'] for o in overlays]
    for s in keep:
        s['at_cut'] = any(abs(s['t'] - c) <= 0.15 for c in cut_t)
        s['at_overlay'] = any(-0.2 <= s['t'] - o <= 0.3 for o in ov_t)
    mins = max(1e-6, dur / 60)
    kinds = {}
    for s in keep:
        kinds[s.get('kind') or 'unsorted'] = kinds.get(s.get('kind') or 'unsorted', 0) + 1
    out['sfx'] = {'_minutes': round(mins, 4), 'events': keep, 'count': len(keep),
                  'per_minute': round(len(keep) / mins, 2), 'kinds': kinds,
                  'at_cuts_share': round(sum(1 for s in keep if s['at_cut']) / len(keep), 3) if keep else None,
                  'at_overlays_share': round(sum(1 for s in keep if s['at_overlay']) / len(keep), 3) if keep else None,
                  'method': ('sharp onsets (spectral flux, 4 x the local spread) in the Demucs music stem, louder than '
                             '-42 dBFS, off the beat grid; sorted by CLAP (cosine) into whoosh / pop / ding / boom / '
                             'click...; a hit that is part of the music can still slip in')}
    if residue is not None:
        out['sfx'] = residue_report(residue, stems['files'], cuts, overlays, dur, words=words or [],
                                    picture_events=list(flashes) if picture_events is None else picture_events)
    prog(0.85, 'sfx')


def _measure_synced_sounds(env_voc, hop_s, spans, out, stems, video, cuts, words, flashes, dur):
    """Measure clicks aligned with transitions and spoken words."""
    # sounds tied to the picture: a click on each transition, a tick on each word (measured, never assumed)
    try:
        import letitedit.looks.sound_sync as sound_sync
        voice_db = level_in(env_voc, hop_s, spans)[0] if env_voc is not None and spans else None
        out['synced'] = sound_sync.analyse(stems['files']['music'] if stems else video,
                                           voice_db if voice_db is not None else -18.3,
                                           cuts=[c['t'] if isinstance(c, dict) else c for c in cuts],
                                           words=words or [], flashes=flashes, duration=dur, stem=bool(stems))
        out['synced']['voice_dbfs'] = voice_db
    except Exception as e:  # noqa: BLE001
        out['synced_error'] = f'{type(e).__name__}: {e}'[:300]


def analyse(video, info, cuts=(), overlays=(), progress=None, log=None, check=None, separate=True, classify=True,
            words=None, flashes=(), picture_events=None):
    """Speech, loudness, music and sound effects of a video. words: the transcript when the caller has it.
    picture_events: times a sound effect may land on (picture_event_times(report)); flashes count when None."""
    import letitedit.review.checks as checks
    out = {}
    dur = float(info['duration'])
    if not info.get('has_audio'):
        return {'present': False, 'note': 'the file has no sound'}, list(words or [])

    def prog(x, msg=''):
        if progress:
            progress(x, msg)
    # speech
    if words is None:
        try:
            wait_for_renders(log=log, check=check)
            import letitedit.footage.speech as speech
            words = speech.words(str(video))
        except Exception as e:  # noqa: BLE001
            words = []
            out['speech_error'] = f'{type(e).__name__}: {e}'[:300]
    prog(0.15, 'speech')
    spans = speech_spans(words)
    talk = sum(b - a for a, b in spans)
    gaps = [b[0] - a[1] for a, b in zip(spans, spans[1:])]
    out['speech'] = {'words': len(words), 'words_per_minute': round(len(words) / (dur / 60), 1) if dur else None,
                     'words_per_minute_while_talking': round(len(words) / (talk / 60), 1) if talk > 1 else None,
                     'speech_share': round(talk / dur, 3) if dur else None,
                     'pauses_s': {'median': round(float(np.median(gaps)), 2), 'p90': round(float(np.percentile(gaps, 90)), 2),
                                  'p90_within_talk': round(float(np.percentile([g for g in gaps if g < 2.0] or [0.0], 90)), 2),
                                  'over_0_7s': sum(1 for g in gaps if g > 0.7)} if gaps else None,
                     'first_word_s': round(float(words[0]['s']), 2) if words else None,
                     'last_word_s': round(float(words[-1].get('e', words[-1]['s'])), 2) if words else None}
    _measure_loudness(checks, video, out, dur, prog)

    # stems
    stems = None
    if separate:
        try:
            wait_for_renders(log=log, check=check)
            import letitedit.sound.model_tools as model_tools
            stems = model_tools.separate(str(video), parts=['vocals', 'music', 'drums', 'other'])
        except Exception as e:  # noqa: BLE001
            out['stems_error'] = f'{type(e).__name__}: {e}'[:300]
    prog(0.45, 'stems')
    hop_s = HOP / SR
    mix = decode_audio(video)
    mus = voc = None
    if stems:
        mus = decode_audio(stems['files']['music'])
        voc = decode_audio(stems['files']['vocals'])
    env_mix = envelope_db(mix)
    env_mus = envelope_db(mus) if mus is not None else None
    env_voc = envelope_db(voc) if voc is not None else None
    music, beats = _measure_music(log, check, video, separate, prog, env_mus, hop_s, spans, out, env_voc, env_mix, cuts)

    _measure_effects(stems, dur, cuts, flashes, picture_events, info, out, mus, mix, env_mus, env_mix, beats, music, spans, hop_s, log, check, prog, classify, video, overlays, words)

    _measure_synced_sounds(env_voc, hop_s, spans, out, stems, video, cuts, words, flashes, dur)

    return out, words


SFX_RULE = {'novelty': 0.15, 'jump_db': 10.0}


def novelty(path, times, hop=0.1):
    """For each time: how unlike the sound around it (1-2.2 s before and after) the second from just before it sounds,
    as 1 - cosine of CLAP embeddings (laion/clap-htsat-unfused, the index worker's 1 s windows every hop s). Measured
    on letitedit's ground truth (32 effects under music): effects median 0.28, other sharp sounds in the music 0.13."""
    import tempfile
    import letitedit.timeline.made as made
    import letitedit.footage.index_tools as index_tools
    f = Path(tempfile.gettempdir()) / f'sfx-novelty-{abs(hash((str(path), os.path.getmtime(path)))) % 10**12}.npz'
    if not f.exists():
        index_tools._worker.ask('audio', ffmpeg=str(made.ffmpeg_exe()), path=str(path), win_s=1.0, hop_s=hop, out=str(f))
    d = np.load(f)
    starts, emb = d['start'], d['emb'].astype(np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9
    out = []
    for t in times:
        k = int(np.clip(round((t - 0.1) / hop), 0, len(emb) - 1))
        ctx = np.where((np.abs(starts - starts[k]) >= 1.0) & (np.abs(starts - starts[k]) <= 2.2))[0]
        if len(ctx) == 0:
            out.append(0.0)
            continue
        m = emb[ctx].mean(axis=0)
        out.append(float(1 - emb[k] @ (m / (np.linalg.norm(m) + 1e-9))))
    return out


def classify_sfx(video, sfx, stems=None, max_n=40):
    """Each candidate's kind from CLAP (cosine scores, 0.8 s from just before the onset) over SFX_LABELS + NOT_SFX:
    the best label's group, or 'music' / 'speech' when those win."""
    import letitedit.sound.model_tools as model_tools
    src = stems['files']['music'] if stems else str(video)
    labels = SFX_LABELS + NOT_SFX
    for s in sfx[:max_n]:
        a = max(0.0, s['t'] - 0.08)
        try:
            r = model_tools.hear(src, start=a, end=a + 0.8, every_s=0.8, window_s=0.8, labels=labels,
                                 top=len(labels), score='cosine')
        except Exception as e:  # noqa: BLE001
            s['kind_error'] = str(e)[:120]
            continue
        seg = (r.get('segments') or [{}])[0]
        ranked = seg.get('labels') or []
        if not ranked:
            continue
        lab, sc = ranked[0]
        s['heard'] = [[l, round(float(v), 3)] for l, v in ranked[:3]]
        scores = {l: float(v) for l, v in ranked}
        s['music_score'] = round(scores.get('music', 0.0), 3)
        s['sfx_score'] = round(max([v for l, v in scores.items() if l in SFX_GROUP] or [0.0]), 3)
        if lab in ('music', 'singing'):
            s['kind'] = 'music'
        elif lab in ('a man speaking', 'a woman speaking'):
            s['kind'] = 'speech'
        elif lab in ('silence', 'room noise'):
            s['kind'] = 'unsorted'
        else:
            s['kind'] = SFX_GROUP.get(lab, lab)
    return sfx


def gate_sfx(sfx, visual_times, music_share, near_s=0.12, picture_events=None):
    """In a video with music (music_share >= 0.3) a sharp sound counts as a sound effect only when it lands on
    something in the picture (a cut, a transition, a zoom, text or a pop-up coming or going, within near_s) or the
    jumps 6 dB or more over the music in the second before (and the sound model calls it an effect). Whooshes found
    as a high-frequency ramp into a cut always count. Without much music every candidate the sound model doesn't call
    music or speech stays. Returns the sfx dict with events filtered and recounted."""
    if sfx.get('by') == 'residue':
        # found in the residue: decided again with the picture events known by now (picture_event_times(report))
        if picture_events is None or '_candidates' not in sfx:
            return sfx
        ans = residue_answer(sfx['_candidates'], float(sfx['_minutes']) * 60, picture_events=picture_events)
        out = _residue_summary(ans, None, None, float(sfx['_minutes']) * 60)
        for s in out['events'] + out['not_sure']:
            s['on_picture_event'] = bool(s.get('on_picture_event'))
        out['_candidates'] = sfx['_candidates']
        out['checked'] = {**sfx.get('checked', {}), **out['checked'], 'picture_events': len(picture_events)}
        anchors = dict(sfx.get('_anchors') or {})
        cut_set = {round(float(c), 3) for c in anchors.get('cuts') or []}
        anchors['pictures'] = sorted({round(float(t), 3) for t in list(anchors.get('pictures') or [])
                                      + list(picture_events) + list(visual_times)} - cut_set)   # cuts on their own
        out['_anchors'] = anchors
        landing(out['events'] + out['not_sure'], anchors.get('cuts') or [], anchors['pictures'],
                [{'s': t} for t in anchors.get('words') or []])
        return out
    ev = list(sfx.get('events') or [])
    vt = sorted(visual_times)
    keep = []
    for x in ev:
        near = any(abs(x['t'] - t) <= near_s for t in vt)
        x['on_picture_event'] = near
        if x.get('by') in ('band ramp', 'novelty'):
            keep.append(x)
            continue
        if (music_share or 0) >= 0.3:
            # measured on letitedit edits with and without effects: the sound model scores plain notes as 'a ding'
            # above 'music', so under music only a sharp sound on a picture event that jumps over the music counts
            if not (near and (x.get('jump_db') or 0) >= 6.0 and x.get('kind') not in (None, 'unsorted')):
                continue
        keep.append(x)
    dur_min = sfx.get('_minutes') or 1.0
    kinds = {}
    for x in keep:
        kinds[x.get('kind') or 'unsorted'] = kinds.get(x.get('kind') or 'unsorted', 0) + 1
    out = dict(sfx)
    out.update({'events': keep, 'count': len(keep), 'per_minute': round(len(keep) / max(1e-6, dur_min), 2),
                'kinds': kinds, 'dropped_as_music': len(ev) - len(keep),
                'at_cuts_share': round(sum(1 for x in keep if x.get('at_cut')) / len(keep), 3) if keep else None})
    out['method'] = (out.get('method', '') + '; with music under the video, a sharp sound counts only on a picture '
                     'event (cut, transition, zoom, text or pop-up within 0.12 s) when it jumps 6 dB over the music; '
                     'whooshes: the 3-10 kHz band ramping 9 dB into a cut')
    return out


def band_db(y, lo_hz, hi_hz, sr=SR, hop=HOP, win=1024):
    """Level (dB) of one frequency band every hop samples."""
    if len(y) < win:
        return np.full(1, -120.0)
    n = 1 + (len(y) - win) // hop
    frames = np.lib.stride_tricks.as_strided(y, shape=(n, win), strides=(y.strides[0] * hop, y.strides[0]))
    spec = np.abs(np.fft.rfft(frames * np.hanning(win).astype(np.float32), axis=1)) ** 2
    f = np.fft.rfftfreq(win, 1.0 / sr)
    band = spec[:, (f >= lo_hz) & (f < hi_hz)].sum(axis=1)
    return 10 * np.log10(band + 1e-12)


def whooshes(y, cut_times, sr=SR, rise_db=9.0):
    """Whooshes into cuts: the 3-10 kHz band rises by rise_db or more over the 0.15-0.6 s before a cut against the
    second before that, peaks within 0.4 s before to 0.15 s after it, and is not a single click (the peak's -3 dB
    width is 80 ms or more). [{t (where it starts rising), kind: 'whoosh', at_cut, by: 'band ramp'}]"""
    hop_s = HOP / sr
    hf = band_db(y, 3000, 10000, sr)
    out = []
    for c in cut_times:
        k = int(c / hop_s)
        base = hf[max(0, k - int(1.6 / hop_s)):max(1, k - int(0.6 / hop_s))]
        win = hf[max(0, k - int(0.4 / hop_s)):k + int(0.15 / hop_s)]
        if len(base) < 5 or len(win) < 5:
            continue
        b0 = float(np.median(base))
        j = int(np.argmax(win))
        peak = float(win[j])
        if peak - b0 < rise_db:
            continue
        width = int((win >= peak - 3).sum()) * hop_s
        if width < 0.08:
            continue
        # where it starts: the first point of the window over halfway up
        start = next((q for q in range(len(win)) if win[q] >= b0 + 0.5 * (peak - b0)), j)
        t = (max(0, k - int(0.4 / hop_s)) + start) * hop_s
        out.append({'t': round(t, 3), 'kind': 'whoosh', 'at_cut': True, 'jump_db': round(peak - b0, 1),
                    'by': 'band ramp', 'peak_width_s': round(width, 3)})
    return out


# ---------------------------------------------------------------------------------------------------------------
# T198: sound effects from what is left after separating speech and music (the Demucs drums and other stems), each
# answered found / not sure (with why) and named by its nearest sound in letitedit's CC0 library.

RESIDUE_ON = True                  # analyse() finds sound effects in the stems' residue (False: the older onset rule)
RESIDUE = {
    'stems': ('drums', 'other'),   # Demucs puts added transients and tonal blips here, speech in vocals
    'win': 512,                    # envelope window (23 ms) every HOP samples (11.6 ms)
    'before_s': (0.5, 0.04),       # the background: the median level from 0.5 s to 0.04 s before
    'min_jump_db': 10.0,           # a candidate rises at least this far over its stem's background
    'min_level_db': -45.0,         # and peaks above this level in that stem
    'gap_s': 0.12,                 # candidates closer than this are one event
    'sure_jump_db': 30.0,          # found without any picture event when it rises this far (and isn't music/speech)
    'event_jump_db': 15.0,         # found on a picture event (a transition or flash, a zoom punch, a title) from here
    'unsure_jump_db': 15.0,        # below sure_jump_db and off picture events: not sure from here, else ignored
    'twin_sim': 0.92,              # two onsets with spectra this alike (cosine of band levels) are the same sound
    'music_twins': 4,              # this many twins within music_window_s of an onset: a hit that repeats = music
    'music_window_s': 6.0,
    'splice_ms': 3.0,              # a click this short (ms, sample level) right on a plain cut may be the splice
    'splice_rule': False,          # True: such a click is "not sure" (off: on two held-out sets no plain splice
                                   # surfaced, and on the references the rule held back typewriter keys on cuts)
    'cut_tol_frames': 2.0,
    'cut_tol_s': 0.05,             # cut times from a sampled picture: at least this close counts as on the cut
    'event_tol_s': 0.15,
    'repeat_sim': 0.95,            # the same sound reused: band levels of its first 0.35 s this alike
    'voice_over_db': 8.0,          # the residue must be this much louder than the voice at that moment
    'grid_window_s': 4.0,          # the beat-grid test: rises of grid_min_jump_db within this distance
    'grid_min_jump_db': 15.0,
    'grid_tol_s': 0.03,
    'grid_hits': 3,
    'tonal_rise_db': 30.0,         # a tonal blip: narrow peaks rising this far over their own frequency's background,
    'tonal_peak_db': 20.0,         # standing this far over their spectral neighbours,
    'tonal_level_db': -20.0,       # at this level or more (dB per FFT bin)
    'tonal_min_hz': 1000.0,        # its lowest peak at least this high (alert beeps and dings; lower: notes, voices)
}


def _mono_resampled(path, sr=SR):
    return decode_audio(path, sr=sr)


def _env(y, win=None):
    return envelope_db(y, win=win or RESIDUE['win'])


def _bands(y, t, sr=SR, n_bands=24, length_s=0.12):
    """Band levels (dB, 24 log-spaced bands 80 Hz-10 kHz) of the length_s after t: a sound's spectral fingerprint."""
    a = max(0, int(t * sr))
    seg = y[a:a + int(length_s * sr)]
    if len(seg) < 256:
        return np.full(n_bands, -120.0)
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
    f = np.fft.rfftfreq(len(seg), 1.0 / sr)
    edges = np.geomspace(80, min(10000, sr / 2 - 1), n_bands + 1)
    return np.array([10 * np.log10(spec[(f >= lo) & (f < hi)].sum() + 1e-12) for lo, hi in zip(edges, edges[1:])])


def _cos(a, b):
    a = a - a.mean()
    b = b - b.mean()
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def residue_onsets(env, hop_s, settings=None):
    """Rises of one stem's envelope over its own background: [(t onset, k peak index, jump dB, peak dB)]."""
    p = {**RESIDUE, **(settings or {})}
    n = len(env)
    b0, b1 = int(p['before_s'][0] / hop_s), int(p['before_s'][1] / hop_s)
    from scipy.ndimage import median_filter
    # background before each hop: the median of the window [k - b0, k - b1)
    med = median_filter(env, size=max(3, b0 - b1) | 1, mode='nearest')
    shift = (b0 + b1) // 2
    bg = np.r_[np.full(shift, med[0]), med[:n - shift]] if n > shift else med
    ahead = np.maximum.reduce([np.r_[env[i:], np.full(i, -120.0)] for i in range(3)])
    jump = ahead - bg
    out = []
    gap = max(1, int(p['gap_s'] / hop_s))
    k = 1
    while k < n - 1:
        if jump[k] >= p['min_jump_db'] and ahead[k] >= p['min_level_db']:
            j = min(n, k + gap)
            m = k + int(np.argmax(jump[k:j]))
            peak = m + int(np.argmax(env[m:m + 4]))
            # onset: the first hop from m back that is under halfway up
            half = bg[m] + 0.5 * (env[peak] - bg[m])
            s = peak
            while s > max(0, m - 6) and env[s - 1] >= half:
                s -= 1
            out.append((s * hop_s, peak, float(jump[m]), float(env[peak])))
            k = m + gap
        else:
            k += 1
    return out


def decide_residue(x, settings=None):
    """('found' | 'not_sure' | 'no', why) for one measured residue candidate (residue_sfx's measures)."""
    p = {**RESIDUE, **(settings or {})}
    if p.get('method') == 2:
        return decide_residue2(x, p)
    j, pic = x['jump_db'], x['on_picture_event']
    if x['by'] == 'tonal':
        if min(x.get('peaks_hz') or [0]) < p['tonal_min_hz']:
            return 'no', 'a low tone: a note of the music or a voice'
        if x['level_db'] - x['voice_db'] < p['voice_over_db']:
            return 'no', 'no louder than the voice at that moment'
        if x.get('repeat_regular'):
            return 'no', 'the same tone repeats with the beat: part of the music'
        if x.get('repeats', 0) >= 1 or pic:
            return 'found', ('a beep or ding' + (f' reused {x["repeats"]} more times off the beat'
                                                if x.get('repeats') else ' on a picture event'))
        return 'not_sure', 'a high tone heard once: a beep or ding, or a note of the music'
    if x['level_db'] - x['voice_db'] < p['voice_over_db']:
        return 'no', 'no louder than the voice at that moment: a syllable, a breath or sound under the speech'
    if x['twins'] >= p['music_twins'] or x.get('repeat_regular') or x.get('on_grid'):
        return 'no', 'the same sound repeats with the beat: part of the music'
    if p.get('splice_rule') and x['on_cut'] and not pic and x['click_ms'] <= p['splice_ms']:
        return 'not_sure', ('a click a few samples long right on a plain cut: an added cut click or just the splice '
                            "where two clips' sound meet")
    if j >= p['sure_jump_db'] or (pic and j >= p['event_jump_db']):
        return 'found', 'rises over the separated speech and music' + (' on a picture event' if pic else '')
    if j >= p['unsure_jump_db']:
        return 'not_sure', "a weaker rise with nothing in the picture at that moment: an added sound or the scene's own"
    return 'no', 'too small'


RESIDUE2 = {
    'method': 2,
    'stems': ('rest', 'drums', 'other'),   # the voice-free rest stem as well as drums and other
    'under_rest_vs_voice_db': -15.0,       # under the voice: the rest stem at most this far under the voice...
    'under_jump_db': 20.0,                 # ...rising this far over its stem's background...
    'under_clap_margin': 0.2,              # ...and CLAP hearing an effect over music and speech by this much
    'clap_veto': None,                     # a strong rise CLAP hears as music or speech by this margin: not sure
    'splice_rule': True,                   # False: a one-sample click on a plain cut is judged like any other sound
}


def decide_residue2(x, p):
    """The second method (T198 2d step 2): decide_residue's rules, with two changes. A sound mixed under the voice
    (no louder than it) may still be found when the voice-free rest stem carries it, it rises under_jump_db and
    CLAP hears an effect rather than music or speech (clap_margin). clap_veto turns a strong rise CLAP hears as music
    or speech into "not sure"; splice_rule False drops the splice rule."""
    j, pic = x['jump_db'], x['on_picture_event']
    margin = x.get('clap_margin')
    if x['by'] == 'tonal' or x['level_db'] - x['voice_db'] >= p['voice_over_db']:
        q = dict(p, method=1, splice_ms=p['splice_ms'] if p.get('splice_rule', True) else -1.0)
        st, why = decide_residue(x, q)
        if st == 'found' and p.get('clap_veto') is not None and margin is not None and margin < p['clap_veto']:
            return 'not_sure', why + '; but it sounds like music or speech'
        return st, why
    # under the voice
    if x['twins'] >= p['music_twins'] or x.get('repeat_regular') or x.get('on_grid'):
        return 'no', 'the same sound repeats with the beat: part of the music'
    rv = x.get('rest_db', -120.0) - x['voice_db']
    if rv < p['under_rest_vs_voice_db'] or j < p['under_jump_db'] or margin is None:
        return 'no', 'under the voice and not clear in the voice-free sound'
    if margin >= p['under_clap_margin']:
        return 'found', f"under the voice, heard as {x.get('clap_kind')} (CLAP margin {margin:.2f})"
    if margin >= p['under_clap_margin'] - 0.05 and (pic or x['on_cut']):
        return 'not_sure', f"under the voice on a picture event or cut; CLAP is unsure ({margin:.2f})"
    return 'no', 'under the voice, and CLAP hears music or speech'


def _on_grid(x, cands, settings=None):
    """True when other rises around x keep a steady beat through it: for some gap g (0.2-1.3 s) to a neighbour,
    grid_hits or more neighbours land within grid_tol_s of x.t + k * g (k = +-1..4). A drum pattern, not an effect."""
    p = {**RESIDUE, **(settings or {})}
    t = float(x['t'])
    nb = np.array([float(o['t']) for o in cands if o is not x and o.get('by') == 'onset'
                   and abs(float(o['t']) - t) <= p['grid_window_s']
                   and float(o['jump_db']) >= p['grid_min_jump_db'] and abs(float(o['t']) - t) > 0.05])
    if len(nb) < p['grid_hits']:
        return False
    best = 0
    for g in np.abs(nb - t):
        if not 0.2 <= g <= 1.3:
            continue
        grid = t + g * np.array([k for k in range(-4, 5) if k])
        hits = sum(1 for q in grid if float(np.min(np.abs(nb - q))) <= p['grid_tol_s'])
        best = max(best, hits)
    return best >= p['grid_hits']


def _click_span(y, t, sr=SR):
    """How long a click lasts at sample level: from the first to the last sample of the high-passed sound within 25 ms
    that reaches a fifth of its peak (s). A splice between two clips is one or two samples wide."""
    a, b = max(0, int((t - 0.02) * sr)), int((t + 0.06) * sr)
    d = np.abs(np.diff(y[a:b]))
    if len(d) < 8:
        return 0.0
    m = int(np.argmax(d))
    lo, hi = max(0, m - int(0.025 * sr)), min(len(d), m + int(0.025 * sr))
    idx = np.where(d[lo:hi] >= 0.2 * d[m])[0]
    return float(idx[-1] - idx[0] + 1) / sr if len(idx) else 0.0


def _regular(times, tol=0.06):
    """True when three or more times keep one beat: every gap is close to a whole number of the smallest gap."""
    ts = sorted(times)
    if len(ts) < 3:
        return False
    gaps = np.diff(ts)
    g0 = float(np.min(gaps))
    if g0 < 0.15:
        return False
    k = np.round(gaps / g0)
    return bool(np.all(np.abs(gaps - k * g0) <= tol * max(1.0, g0 / 0.5)))


def residue_tonal(y, sr=SR, settings=None):
    """Tonal blips (beeps, dings): two or more narrow spectral peaks rising together tonal_rise_db or more over their
    own frequency's level in the 0.5 s before, standing tonal_peak_db over their spectral neighbours. Each blip says
    which peaks (Hz) and how many other blips in the video share them (recurs: the same sound reused).
    [{t, peaks_hz, rise_db, recurs, recur_times}]"""
    p = {**RESIDUE, **(settings or {})}
    hop, win = HOP, 2048
    if len(y) < win * 2:
        return []
    from scipy.ndimage import median_filter, maximum_filter1d
    n = 1 + (len(y) - win) // hop
    fr = np.lib.stride_tricks.as_strided(y, shape=(n, win), strides=(y.strides[0] * hop, y.strides[0]))
    P = 10 * np.log10(np.abs(np.fft.rfft(fr * np.hanning(win).astype(np.float32), axis=1)) ** 2 + 1e-12)
    f = np.fft.rfftfreq(win, 1.0 / sr)
    hop_s = hop / sr
    span = int(0.5 / hop_s)
    bg = median_filter(P, size=(span | 1, 1), mode='nearest')
    sh = span // 2 + int(0.04 / hop_s)
    bg = np.r_[np.repeat(bg[:1], sh, 0), bg[:-sh]]
    R = P - bg
    # a narrow peak: higher than the bins 3-8 away on both sides by tonal_peak_db
    side = np.maximum(np.roll(maximum_filter1d(P, 6, axis=1), 6, axis=1), np.roll(maximum_filter1d(P, 6, axis=1), -6, axis=1))
    peaky = (P - side >= p['tonal_peak_db']) & (R >= p['tonal_rise_db']) & (P >= p['tonal_level_db'])
    peaky[:, f < 150] = False
    count = peaky.sum(axis=1)
    out = []
    k = 0
    gap = int(p['gap_s'] / hop_s)
    while k < n:
        if count[k] >= 2:
            j = min(n, k + int(0.08 / hop_s))
            m = k + int(np.argmax(count[k:j]))
            bins = np.where(peaky[k:j].any(axis=0))[0]
            # keep one bin per peak (adjacent bins are the same peak)
            groups = np.split(bins, np.where(np.diff(bins) > 2)[0] + 1) if len(bins) else []
            pk = [int(g[np.argmax(P[m, g])]) for g in groups if len(g)]
            out.append({'t': k * hop_s, 'bins': pk, 'peaks_hz': [int(round(f[b])) for b in pk],
                        'rise_db': round(float(np.max(R[k:j][:, pk])), 1) if pk else 0.0})
            k = m + gap
        else:
            k += 1
    for x in out:
        same = [o['t'] for o in out if o is not x and abs(o['t'] - x['t']) > 0.3
                and len(set(x['bins']) & {b + d for b in o['bins'] for d in (-1, 0, 1)}) >= 2]
        x['recurs'] = len(same)
        x['recur_times'] = [round(t, 2) for t in same[:10]]
        x['recur_regular'] = _regular([x['t']] + same)
    for x in out:
        x.pop('bins', None)
    return out


def _tonal_groups(blips, join_s=0.6):
    """Blips that share two peaks and follow within join_s are one sound (a beep-beep-beep); recurs = how many other
    groups share its peaks, recur_regular = whether those repeats keep a beat."""
    def share(a, b):
        return len({round(h / 12) for h in a} & {round(h / 12) + d for h in b for d in (-1, 0, 1)}) >= 2
    groups = []
    for b in sorted(blips, key=lambda x: x['t']):
        g = groups[-1] if groups else None
        if g and b['t'] - g['end'] <= join_s and share(b['peaks_hz'], g['peaks_hz']):
            g['end'] = b['t'] + 0.12
            g['blips'] += 1
            g['rise_db'] = max(g['rise_db'], b['rise_db'])
        else:
            groups.append({'t': b['t'], 'end': b['t'] + 0.12, 'peaks_hz': b['peaks_hz'], 'rise_db': b['rise_db'],
                           'blips': 1})
    for g in groups:
        same = [o['t'] for o in groups if o is not g and share(g['peaks_hz'], o['peaks_hz'])]
        g['recurs'] = len(same)
        g['recur_regular'] = _regular([g['t']] + same)
    return groups


def _one_per_sound(found, unsure, cap_s=0.6):
    """One answer per sound: an event starting inside an earlier one's span (capped at cap_s) is the same sound;
    found wins over not sure, then the bigger rise."""
    allx = sorted([(x, 'found') for x in found] + [(x, 'not_sure') for x in unsure], key=lambda q: q[0]['t'])
    kept = []
    for x, st in allx:
        if kept:
            y, sty = kept[-1]
            if x['t'] < y['t'] + min(cap_s, max(0.12, y['end'] - y['t'])):
                better = (st == 'found' and sty != 'found') or (st == sty and x['jump_db'] > y['jump_db'])
                if better:
                    kept[-1] = (x, st)
                continue
        kept.append((x, st))
    return [x for x, st in kept if st == 'found'], [x for x, st in kept if st == 'not_sure']


def _near(t, times, tol):
    return bool(len(times)) and float(np.min(np.abs(np.asarray(times) - t))) <= tol


def residue_sfx(stem_files, mix=None, duration=None, cuts=(), picture_events=(), fps=30.0, settings=None):
    """Sound effects in the residue of a separated soundtrack.

    stem_files: {'vocals', 'drums', 'other'[, 'bass']: WAV paths} (model_tools.separate). cuts: plain cut times;
    picture_events: times of flashes, transitions, zooms, text and overlays arriving or leaving. Returns
    {'events': [found], 'not_sure': [with why], 'checked': {...}, 'method'}; every event has t, end, stem, jump_db,
    level_db, width_s, at_cut, on_picture_event, twins, and 'why'."""
    p = {**RESIDUE, **(settings or {})}
    hop_s = HOP / SR
    st = {k: _mono_resampled(v) for k, v in stem_files.items() if k in ('vocals', 'drums', 'other', 'bass', 'rest')}
    if not all(k in st for k in ('vocals', 'drums', 'other')):
        raise ValueError('residue_sfx needs the vocals, drums and other stems')
    dur = float(duration or len(st['vocals']) / SR)
    env = {k: _env(v) for k, v in st.items()}
    resid = st['drums'] + st['other']
    cuts = sorted(float(c) for c in cuts)
    pics = sorted(float(c) for c in picture_events)
    cut_tol = max(p['cut_tol_s'], p['cut_tol_frames'] / max(1.0, float(fps or 30.0)))
    # 1. onsets per stem, merged across stems (the strongest rise wins)
    cands = []
    for name in p['stems']:
        for t, k, jump, lvl in residue_onsets(env[name], hop_s, p):
            cands.append({'t': t, 'k': k, 'stem': name, 'jump_db': jump, 'level_db': lvl, 'by': 'onset'})
    cands.sort(key=lambda c: c['t'])
    merged = []
    for c in cands:
        if merged and c['t'] - merged[-1]['t'] < p['gap_s']:
            if c['jump_db'] > merged[-1]['jump_db']:
                merged[-1] = c
            continue
        merged.append(c)
    # tonal blips (beeps, dings), grouped: blips sharing their peaks less than 0.6 s apart are one sound
    for g in _tonal_groups(residue_tonal(st['other'], settings=p)):
        merged.append({'t': g['t'], 'k': int(g['t'] / hop_s) + 2, 'stem': 'other', 'jump_db': g['rise_db'],
                       'level_db': float(env['other'][min(int(g['t'] / hop_s) + 2, len(env['other']) - 1)]),
                       'by': 'tonal', 'tonal': g})
    merged.sort(key=lambda c: c['t'])
    # 2. fingerprints for repetition (a hit that recurs with the beat is part of the music)
    for c in merged:
        y = st[c['stem']] if c['stem'] in st else resid
        c['_fp'] = _bands(y, c['t'])
        c['_lfp'] = np.r_[_bands(y, c['t'], length_s=0.1), _bands(y, c['t'] + 0.1, length_s=0.1),
                          _bands(y, c['t'] + 0.2, length_s=0.15)]
    measured = []
    b0, b1 = int(p['before_s'][0] / hop_s), int(p['before_s'][1] / hop_s)
    for c in merged:
        t, k = c['t'], c['k']
        if t < 0.02 or t > dur - 0.05:
            continue
        e = env[c['stem']] if c['stem'] in env else _env(resid)
        peak_db = float(e[min(k, len(e) - 1)])
        width = int((e[max(0, k - 10):k + 40] >= peak_db - 6).sum()) * hop_s
        # the end: where the stem falls back within 3 dB of its background
        bg = float(np.median(e[max(0, k - b0):max(1, k - b1)]))
        j = k
        while j < min(len(e) - 1, k + int(3.0 / hop_s)) and e[j] > bg + 3:
            j += 1
        end = max(t + 0.03, j * hop_s)
        # its shape: how long it takes to peak, and to fall 20 dB below the peak (a click is gone in a few ms)
        q = k
        while q < min(len(e) - 1, k + int(2.0 / hop_s)) and e[q] > peak_db - 20:
            q += 1
        rise_s, decay_s = max(0.0, k * hop_s - t), (q - k) * hop_s
        # the voice: how far the vocals stem rises at the same moment
        kv0, kv1 = int(t / hop_s), int(t / hop_s) + 4
        vbg = float(np.median(env['vocals'][max(0, kv0 - b0):max(1, kv0 - b1)]))
        vjump = float(np.max(env['vocals'][kv0:kv1]) - vbg) if kv1 <= len(env['vocals']) else 0.0
        vlevel = float(np.max(env['vocals'][kv0:kv1])) if kv1 <= len(env['vocals']) else -120.0
        # the voice-free sound (rest = the input minus the vocals stem): how far it stands out over its own background
        if 'rest' in env:
            er = env['rest']
            rbg = float(np.median(er[max(0, kv0 - b0):max(1, kv0 - b1)]))
            rlevel = float(np.max(er[kv0:kv0 + 4])) if kv0 + 4 <= len(er) else -120.0
            rest_m = {'rest_jump_db': round(rlevel - rbg, 1), 'rest_db': round(rlevel, 1)}
        else:
            rest_m = {}
        twins = sum(1 for o in merged if o is not c and o['stem'] == c['stem']
                    and abs(o['t'] - t) <= p['music_window_s'] and _cos(o['_fp'], c['_fp']) >= p['twin_sim'])
        # the same sound again anywhere in the video (an effect reused), and whether those repeats keep a beat
        again = sorted(o['t'] for o in merged if o is not c and o['stem'] == c['stem'] and abs(o['t'] - t) > 0.3
                       and _cos(o['_lfp'], c['_lfp']) >= p['repeat_sim'])
        span = _click_span(st[c['stem']] if c['stem'] in st else resid, t)
        at_cut = _near(t, cuts, cut_tol) or _near(t + 0.5 * width, cuts, cut_tol)
        on_pic = _near(t, pics, p['event_tol_s'])
        x = {'t': round(t, 3), 'end': round(end, 3), 'stem': c['stem'], 'by': c['by'],
             'jump_db': round(c['jump_db'], 1), 'level_db': round(peak_db, 1), 'width_s': round(width, 3),
             'voice_jump_db': round(vjump, 1), 'voice_db': round(vlevel, 1), 'twins': twins,
             'repeats': len(again), 'repeat_regular': _regular([t] + again), 'bg_db': round(bg, 1),
             'click_ms': round(span * 1000, 1), 'rise_s': round(rise_s, 3), 'decay_s': round(decay_s, 3),
             'on_cut': at_cut, 'on_picture_event': on_pic, **rest_m}
        if c.get('tonal'):
            g = c['tonal']
            x.update({'end': round(max(x['t'] + 0.05, g['end']), 3), 'peaks_hz': g['peaks_hz'],
                      'repeats': g['recurs'], 'repeat_regular': g['recur_regular'], 'blips': g['blips']})
        measured.append(x)
    for x in measured:
        x['on_grid'] = _on_grid(x, measured, p)
    out = residue_answer(measured, dur, settings=p)
    out['checked'].update({'stems': list(p['stems']) + ['other (tones)'], 'candidates': len(measured),
                           'cuts': len(cuts), 'picture_events': len(pics)})
    out['candidates'] = measured
    return out


def residue_answer(candidates, duration, picture_events=None, settings=None):
    """Decide measured residue candidates (residue_sfx): found / not sure, one answer per sound. picture_events:
    when given, each candidate's on_picture_event is measured again against these times (titles known later)."""
    p = {**RESIDUE, **(settings or {})}
    pics = sorted(float(t) for t in picture_events) if picture_events is not None else None
    found, unsure = [], []
    for x in candidates:
        if pics is not None:
            x['on_picture_event'] = _near(float(x['t']), pics, p['event_tol_s'])
        status, why = decide_residue(x, p)
        x['status'], x['why'] = status, why
        if status == 'found':
            found.append(x)
        elif status == 'not_sure':
            unsure.append(x)
    found, unsure = _one_per_sound(found, unsure)
    mins = max(1e-6, float(duration) / 60)
    return {'events': found, 'not_sure': unsure, 'count': len(found), 'per_minute': round(len(found) / mins, 2),
            'checked': {'duration_s': round(float(duration), 2), 'complete': True},
            'method': ('rises of the Demucs drums and other stems over their own background, and high tones (beeps, '
                       'dings) rising in the other stem; kept when louder than the voice at that moment and not '
                       'repeating with a beat; a sound right on a picture event (a transition, a zoom punch, a title) '
                       'counts from a smaller rise; a click a few samples long on a plain cut, and weaker rises or '
                       'tones heard once with nothing in the picture, are "not sure"')}


def picture_event_times(report, titles=True):
    """The picture events of an importer report that a sound effect can land on: transitions and flashes, zoom punches
    and (titles=True) titles and labels arriving. Caption words popping in and overlays are left out: on a captioned
    video they are nearly continuous, so landing on one says nothing."""
    ev = [float(g.get('start', g['t'])) for g in report.get('transitions') or [] if g.get('t') is not None]
    ev += [float(z['t']) for z in report.get('zooms') or [] if z.get('kind') in ('punch_in', 'punch_out')]
    if titles:
        ev += [float(e['t']) for e in report.get('text_events') or [] if e.get('role') in ('title', 'label')]
    return sorted(ev)


LANDS_WITHIN_S = 0.5      # the nearest cut, picture change or word onset within this distance is what a sound lands on


def landing(events, cuts=(), pictures=(), words=(), within_s=LANDS_WITHIN_S):
    """What each sound lands on: x['lands_on'] = {'cut' | 'picture' | 'word': {'t', 'offset_ms'}} for the nearest of each
    within within_s, and 'nearest': the closest of them (or None). offset_ms = the sound's onset minus that moment:
    negative = the sound comes early. Pictures are picture changes (transitions, zoom punches, titles, text, stickers
    and overlays arriving); words are the transcript's word onsets."""
    sets = {'cut': sorted(float(c['t'] if isinstance(c, dict) else c) for c in cuts),
            'picture': sorted(float(p) for p in pictures),
            'word': sorted(float(w['s']) for w in words if isinstance(w, dict) and w.get('s') is not None)}
    for x in events:
        t = float(x['t'])
        lands = {}
        for kind, times in sets.items():
            if not times:
                continue
            arr = np.asarray(times)
            i = int(np.argmin(np.abs(arr - t)))
            if abs(arr[i] - t) <= within_s:
                lands[kind] = {'t': round(float(arr[i]), 3), 'offset_ms': int(round((t - arr[i]) * 1000))}
        near = min(lands, key=lambda k: abs(lands[k]['offset_ms'])) if lands else None
        x['lands_on'] = {**lands, 'nearest': near}
    return events


def residue_report(residue, stem_files, cuts, overlays, duration, words=(), picture_events=()):
    """analyse()'s sfx section from residue_sfx: the found events (named, with at_cut and at_overlay as before), the
    not sure ones apart, and the candidates a picture event could still decide (for gate_sfx, once titles are known)."""
    keep = [x for x in residue['candidates'] if decide_residue(dict(x, on_picture_event=True))[0] != 'no']
    try:
        name_sfx(keep, stem_files)
    except Exception as e:  # noqa: BLE001
        for x in keep:
            x.setdefault('kind', 'unsorted')
            x['kind_error'] = f'{type(e).__name__}: {e}'[:120]
    cut_t = [c['t'] if isinstance(c, dict) else c for c in cuts]
    ov_t = [o['t'] for o in overlays]
    for s in keep:
        s['at_cut'] = any(abs(s['t'] - c) <= 0.15 for c in cut_t)
        s['at_overlay'] = any(-0.2 <= s['t'] - o <= 0.3 for o in ov_t)
    out = _residue_summary(residue_answer(keep, duration), cut_t, ov_t, duration)
    out['_anchors'] = {'cuts': [round(c, 3) for c in cut_t], 'pictures': sorted(round(float(t), 3) for t in
                                                                             list(picture_events) + ov_t),
                       'words': [round(float(w['s']), 3) for w in words or [] if isinstance(w, dict) and 's' in w]}
    landing(out['events'] + out['not_sure'], out['_anchors']['cuts'], out['_anchors']['pictures'],
            [{'s': t} for t in out['_anchors']['words']])
    out['_candidates'] = keep
    out['checked']['candidates_measured'] = len(residue['candidates'])
    return out


def _residue_summary(ans, cut_t, ov_t, duration):
    events = ans['events']
    for s in events + ans['not_sure']:
        if cut_t is not None:
            s['at_cut'] = any(abs(s['t'] - c) <= 0.15 for c in cut_t)
        if ov_t is not None:
            s['at_overlay'] = any(-0.2 <= s['t'] - o <= 0.3 for o in ov_t)
        s.setdefault('kind', 'unsorted')
        s.setdefault('at_cut', False)
        s.setdefault('at_overlay', False)
    kinds = {}
    for s in events:
        kinds[s['kind']] = kinds.get(s['kind'], 0) + 1
    mins = max(1e-6, float(duration) / 60)
    return {'_minutes': round(mins, 4), 'by': 'residue', 'events': events, 'count': len(events),
            'per_minute': round(len(events) / mins, 2), 'kinds': kinds,
            'at_cuts_share': round(sum(1 for s in events if s['at_cut']) / len(events), 3) if events else None,
            'at_overlays_share': round(sum(1 for s in events if s['at_overlay']) / len(events), 3) if events else None,
            'not_sure': ans['not_sure'], 'not_sure_count': len(ans['not_sure']), 'checked': ans['checked'],
            'method': ans['method'] + "; named by the nearest sound among the CC0 library's edit effects"}


# what a candidate sounds like: CLAP (laion/clap-htsat-unfused, model_tools' "hear") scores against plain labels
CLAP_SFX = {'whoosh': 'a whoosh', 'riser': 'a riser, a rising sweep', 'hit': 'a hit or an impact',
            'keys': 'typewriter keys or keyboard typing', 'shutter': 'a camera shutter', 'pop': 'a pop sound effect',
            'ding': 'a ding or a notification sound', 'record scratch': 'a record scratch', 'click': 'a click',
            'foley': 'liquid pouring or a can opening'}
CLAP_NOT = {'music': 'music', 'speech': 'a person speaking'}
CLAP_WINDOW_S = 0.6


def clap_sfx(events, audio_path, window_s=CLAP_WINDOW_S):
    """Score each event (its window_s from 0.05 s before t, in audio_path, e.g. the voice-free rest stem) against
    CLAP_SFX and CLAP_NOT (cosine of the sound and text embeddings). Sets x['clap'] = {label key: cosine} and
    x['clap_kind'], x['clap_margin'] (the best effect label minus the better of music and speech). One model call for
    every event of the file. GPU: model_tools takes its own turn on the PC lock."""
    if not events:
        return events
    import tempfile
    import letitedit.sound.model_tools as model_tools
    keys = list(CLAP_SFX) + list(CLAP_NOT)
    texts = ['This is a sound of {}.'.replace('{}', {**CLAP_SFX, **CLAP_NOT}[k]) for k in keys]
    with tempfile.TemporaryDirectory() as d:
        wav = model_tools._decode(str(audio_path), str(Path(d) / 'clap.wav'), 0, None, 48000, 1)
        length = model_tools._wav_seconds(wav)
        windows = [[round(max(0.0, float(x['t']) - 0.05), 4), round(min(length, max(0.0, float(x['t']) - 0.05)
                                                                         + window_s), 4)] for x in events]
        reply = model_tools._clap_job(wav, windows, texts, length)
    for x, row in zip(events, reply['cosine']):
        sc = {k: round(float(v), 4) for k, v in zip(keys, row)}
        best = max(CLAP_SFX, key=lambda k: sc[k])
        x['clap'] = sc
        x['clap_kind'] = best
        x['clap_margin'] = round(sc[best] - max(sc['music'], sc['speech']), 4)
    return events


# naming: the nearest sound in letitedit's CC0 library (assets\manifest: sfx-library, kenney-sfx, synth-sfx)
LIBRARY_MANIFESTS = ('sfx-library', 'kenney-sfx', 'synth-sfx')
LIBRARY_CACHE = None          # where the library's fingerprints are kept (None: <cache>\sfx-library-fingerprints.npz)
KIND_WORDS = [                # library category words -> the kind reported (first match wins)
    ('downlifter', 'downlifter'), ('tape', 'downlifter'), ('reverse', 'riser'), ('riser', 'riser'),
    ('uplift', 'riser'), ('build', 'riser'), ('whoosh', 'whoosh'), ('swoosh', 'whoosh'), ('swipe', 'whoosh'),
    ('zoom', 'whoosh'), ('shutter', 'shutter'), ('camera', 'shutter'), ('typing', 'keyboard'), ('key', 'keyboard'),
    ('click', 'click'), ('switch', 'click'), ('rollover', 'click'), ('tick', 'click'), ('tap', 'click'),
    ('pop', 'pop'), ('boing', 'pop'), ('bubble', 'pop'), ('ding', 'ding'), ('bell', 'ding'), ('chime', 'ding'),
    ('notification', 'ding'), ('confirm', 'ding'), ('sparkle', 'ding'), ('level up', 'ding'), ('cash', 'ding'),
    ('beep', 'beep'), ('tone', 'beep'), ('phaser', 'beep'), ('laser', 'glitch'), ('glitch', 'glitch'),
    ('scratch', 'glitch'), ('static', 'glitch'), ('computer', 'glitch'), ('zap', 'glitch'), ('boom', 'hit'),
    ('bass drop', 'hit'), ('impact', 'hit'), ('explosion', 'hit'), ('hit', 'hit'), ('bonk', 'hit'), ('slap', 'hit'),
    ('knock', 'hit'), ('hammer', 'hit'), ('thump', 'hit'), ('rimshot', 'hit'), ('drum', 'hit'), ('heartbeat', 'hit'),
    ('sting', 'sting'), ('fail', 'sting'), ('horn', 'sting'), ('whistle', 'whistle'),
]


def kind_of(category):
    c = (category or '').lower()
    return next((k for w, k in KIND_WORDS if w in c), c or 'unsorted')


def fingerprint(y, t, sr=SR):
    """What a sound is like from t: band levels of its first 0.12 s and of 0.12-0.5 s (shape, relative to their
    mean) and its level every 50 ms for 1 s (relative to its peak). One vector, unit length."""
    a = _bands(y, t, sr)
    b = _bands(y, t + 0.12, sr, length_s=0.38)
    s0 = max(0, int(t * sr))
    seg = y[s0:s0 + sr]
    step = int(0.05 * sr)
    lv = np.array([10 * np.log10(np.mean(seg[i:i + step] ** 2) + 1e-12) if len(seg[i:i + step]) else -120.0
                   for i in range(0, sr, step)])
    lv = np.maximum(lv - lv.max(), -60.0) / 60.0
    v = np.r_[(a - a.mean()) / 20.0, (b - b.mean()) / 20.0, 0.5 * (b.mean() - a.mean()) / 20.0, lv]
    return v / (np.linalg.norm(v) + 1e-9)


def library_fingerprints(root=None):
    """(ids, categories, kinds, matrix) for every sound of the CC0 library, made once and kept."""
    import json as _json
    root = Path(root or os.environ.get('LETITEDIT_ROOT') or Path(__file__).resolve().parents[3])
    cache = Path(LIBRARY_CACHE) if LIBRARY_CACHE else root / 'cache' / 'sfx-library-fingerprints.npz'
    items = []
    for m in LIBRARY_MANIFESTS:
        f = root / 'assets' / 'manifest' / f'{m}.json'
        if f.exists():
            items += _json.loads(f.read_text(encoding='utf-8')).get('items') or []
    items = [i for i in items if (root / i['file']).exists()]
    key = str(len(items)) + '|' + '|'.join(sorted(i['id'] for i in items))[:4000]
    if cache.exists():
        d = np.load(cache, allow_pickle=False)
        if str(d['key']) == key:
            return list(d['ids']), list(d['cats']), [kind_of(c) for c in d['cats']], d['fp']
    ids, cats, fps = [], [], []
    for i in items:
        y = decode_audio(root / i['file'], duration=2.0)
        if len(y) < 512:
            continue
        ids.append(i['id'])
        cats.append(i.get('category') or '')
        fps.append(fingerprint(y, max(0.0, float(i.get('onset_s') or 0.0))))
    fp = np.array(fps, np.float32)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache, key=key, ids=np.array(ids), cats=np.array(cats), fp=fp)
    return ids, cats, [kind_of(c) for c in cats], fp


EDIT_KINDS = ('whoosh', 'riser', 'downlifter', 'click', 'shutter', 'keyboard', 'pop', 'ding', 'beep', 'glitch',
              'hit', 'sting', 'whistle')
TONAL_KINDS = ('beep', 'ding')


def name_sfx(events, stem_files, top=3, root=None):
    """Name each event by its nearest sounds in the library's edit effects (EDIT_KINDS; the library's voices, animals
    and room sounds are left out), cosine of fingerprints from the drums + other residue. A tonal blip is matched
    among beeps and dings only. Sets kind (the vote of the five nearest), like (the top sfx: references with their
    similarity) and kind_votes."""
    if not events:
        return events
    ids, cats, kinds, lib = library_fingerprints(root)
    edit = np.array([k in EDIT_KINDS for k in kinds])
    tonal = np.array([k in TONAL_KINDS for k in kinds])
    if not edit.any():
        for x in events:
            x['kind'] = 'unsorted'
        return events
    y = _mono_resampled(stem_files['drums']) + _mono_resampled(stem_files['other'])
    for x in events:
        v = fingerprint(y, float(x['t']))
        allowed = tonal if x.get('by') == 'tonal' and tonal.any() else edit
        sim = np.where(allowed, lib @ v, -2.0)
        order = np.argsort(-sim)[:max(top, 5)]
        votes = {}
        for o in order[:5]:
            votes[kinds[o]] = votes.get(kinds[o], 0.0) + float(sim[o])
        x['kind'] = max(votes, key=votes.get)
        x['like'] = [[f'sfx:{ids[o]}', round(float(sim[o]), 3)] for o in order[:top]]
        x['kind_votes'] = {k: round(v_, 2) for k, v_ in sorted(votes.items(), key=lambda kv: -kv[1])}
    return events


# --- Anchored search (T198 2d step 3): the picture says where to listen ------------------------------------------
# Reference editors put an effect on a cut or a picture change, a hair early (median -10 ms), so at every cut,
# picture change and word onset the question is only: does an added sound that isn't speech start 60 ms before to
# 40 ms after it? Two kinds of evidence: the sharpest rise in sound there (the mix, its top band, the vocals stem and
# the voice-free stem), and a frame-level sound event model's effect classes rising over their own level nearby
# (PANNs Cnn14_DecisionLevelMax on AudioSet, run on the mix and on the vocals stem, where Demucs files effects under
# speech). The model's frames are given to anchor_measures; running it is the caller's (a GPU model).

ANCHOR = {
    'early_s': 0.06, 'late_s': 0.04,     # an onset this far before to this far after the anchor counts
    'join_s': 0.03,                      # anchors this close are one (a cut wins over a picture, a picture over a word)
    'env_win_s': 0.004,                  # the rise measure: 4 ms power envelope, every 1 ms,
    'after_s': 0.03, 'before_s': (0.10, 0.01),   # mean over 30 ms from the onset against 100-10 ms before it
    'hi_hz': 2500.0,                     # the top band (clicks, shutters, keys, the hiss of a whoosh)
    'sustain_s': (0.005, 0.04),          # the body of a sound: its level this long after the onset, against before
    'sed_window_s': (0.28, 0.04),        # model segments (0.32 s) starting this far before to after the anchor
    'sed_base_s': (3.0, 0.5),            # each class's own level: median of the segments 0.5-3 s away either side
    'sed_floor': 1e-4,
}
# AudioSet classes kept by the model run (their indices) that are added-sound kinds, and the kind each one suggests
SED_KINDS = {
    459: 'whoosh', 472: 'whoosh', 473: 'whoosh', 497: 'whoosh',
    460: 'hit', 461: 'hit', 466: 'hit', 467: 'hit', 468: 'hit', 469: 'hit', 470: 'hit', 493: 'hit',
    384: 'click', 385: 'click', 407: 'click', 491: 'click', 492: 'click',
    416: 'shutter', 417: 'shutter',
    434: 'pop', 494: 'pop', 498: 'pop',
    205: 'ding', 319: 'ding', 356: 'ding', 481: 'ding', 482: 'ding', 483: 'ding', 484: 'ding', 495: 'ding',
    501: 'ding', 502: 'ding', 503: 'ding', 505: 'ding',
    215: 'glitch', 474: 'glitch', 475: 'glitch',
    378: 'foley', 445: 'foley', 449: 'foley', 465: 'foley', 471: 'foley', 476: 'foley', 477: 'foley', 478: 'foley',
    479: 'foley', 480: 'foley', 485: 'foley', 486: 'foley', 487: 'foley', 488: 'foley', 489: 'foley', 490: 'foley',
    499: 'foley',
    504: 'other',
}
SED_SPEECH, SED_MUSIC = 0, 137
# the library's kinds (KIND_WORDS) grouped like the model's, for one vocabulary of devices
DEVICE_OF_KIND = {'whoosh': 'whoosh', 'riser': 'whoosh', 'downlifter': 'whoosh', 'hit': 'hit', 'click': 'click',
                  'keyboard': 'click', 'shutter': 'shutter', 'pop': 'pop', 'ding': 'ding', 'beep': 'ding',
                  'glitch': 'glitch', 'sting': 'other', 'whistle': 'other'}


def anchor_list(cuts=(), pictures=(), words=(), settings=None):
    """[{'t', 'on': 'cut' | 'picture' | 'word', 'also': [...]}], sorted; anchors within join_s are one."""
    p = {**ANCHOR, **(settings or {})}
    raw = [(float(c['t'] if isinstance(c, dict) else c), 0, 'cut') for c in cuts]
    raw += [(float(t), 1, 'picture') for t in pictures]
    raw += [(float(w['s'] if isinstance(w, dict) else w), 2, 'word') for w in words]
    out = []
    for t, _rank, on in sorted(raw, key=lambda r: (r[1], r[0])):
        near = next((a for a in out if abs(a['t'] - t) <= p['join_s']), None)
        if near:
            if on not in near['also'] and on != near['on']:
                near['also'].append(on)
            continue
        out.append({'t': t, 'on': on, 'also': []})
    return sorted(out, key=lambda a: a['t'])


def _rise_at(y, sr, a, p):
    """The sharpest rise starting in [a - early_s, a + late_s]: (onset t, rise dB, level dB after)."""
    w = max(1, int(p['env_win_s'] * sr))
    step = max(1, int(0.001 * sr))
    lo = max(0, int((a - p['early_s'] - p['before_s'][0] - 0.01) * sr))
    hi = min(len(y), int((a + p['late_s'] + p['after_s'] + 0.01) * sr))
    seg = y[lo:hi].astype(np.float64)
    if len(seg) < 4 * w:
        return a, 0.0, -120.0
    pw = np.convolve(seg ** 2, np.ones(w) / w, 'same')[::step]
    ts = lo / sr + np.arange(len(pw)) * step / sr
    cs = np.r_[0.0, np.cumsum(pw)]
    n_aft = max(1, int(round(p['after_s'] / 0.001)))
    b0, b1 = int(round(p['before_s'][0] / 0.001)), int(round(p['before_s'][1] / 0.001))
    best = (a, -99.0, -120.0)
    for i, t in enumerate(ts):
        if t < a - p['early_s'] or t > a + p['late_s'] or i - b0 < 0 or i + n_aft > len(pw):
            continue
        aft = (cs[i + n_aft] - cs[i]) / n_aft
        bef = (cs[i - b1] - cs[i - b0]) / max(1, b0 - b1)
        r = 10 * np.log10((aft + 1e-12) / (bef + 1e-12))
        if r > best[1]:
            best = (float(t), float(r), float(10 * np.log10(aft + 1e-12)))
    return best


def _sustain_at(y, sr, t, p):
    """How far the sound stays up after an onset at t (dB): the mean power sustain_s after it against before_s
    before it. A splice's click is one sample, so in room tone it barely stays up; a key or a shutter does."""
    def mean_pw(a, b):
        seg = y[max(0, int(a * sr)):max(0, int(b * sr))].astype(np.float64)
        return float(np.mean(seg ** 2)) if len(seg) else 0.0
    after = mean_pw(t + p['sustain_s'][0], t + p['sustain_s'][1])
    before = mean_pw(t - p['before_s'][0], t - p['before_s'][1])
    return float(10 * np.log10((after + 1e-12) / (before + 1e-12)))


def _highpass(y, sr, hz):
    from scipy.signal import butter, sosfilt
    return sosfilt(butter(4, hz, 'highpass', fs=sr, output='sos'), y).astype(np.float32)


def _sed_at(sed, a, p):
    """The model's evidence at an anchor: for each kept class, its peak in the segments around the anchor against its
    own median level 0.5-3 s away (log10 ratio). The best effect class, its ratio and peak, speech's ratio and peak,
    music's peak."""
    t, pr, cls = sed['times'], sed['probs'], list(sed['classes'])
    win = (t >= a - p['sed_window_s'][0]) & (t <= a + p['sed_window_s'][1])
    far = np.abs(t - a)
    base = (far >= p['sed_base_s'][1]) & (far <= p['sed_base_s'][0])
    if not win.any() or not base.any():
        return None
    peak = pr[win].max(axis=0)
    med = np.median(pr[base], axis=0)
    ratio = np.log10((peak + p['sed_floor']) / (med + p['sed_floor']))
    eff = [i for i, c in enumerate(cls) if int(c) in SED_KINDS]
    j = max(eff, key=lambda i: ratio[i])
    sp = cls.index(SED_SPEECH) if SED_SPEECH in cls else None
    mu = cls.index(SED_MUSIC) if SED_MUSIC in cls else None
    return {'cls': int(cls[j]), 'kind': SED_KINDS[int(cls[j])], 'ratio': float(ratio[j]), 'peak': float(peak[j]),
            'speech_ratio': float(ratio[sp]) if sp is not None else 0.0,
            'speech': float(peak[sp]) if sp is not None else 0.0, 'music': float(peak[mu]) if mu is not None else 0.0}


def anchor_measures(audio, stem_files=None, sed=None, anchors=(), settings=None):
    """Measure each anchor (anchor_list) for an added sound starting at it. Per anchor: the rise (dB), level and onset
    in the mix, its top band, and the vocals and rest stems when given; the model's evidence on the mix and the vocals
    stem when given (sed = {'mix' | 'vocals': {'times', 'probs', 'classes'}})."""
    p = {**ANCHOR, **(settings or {})}
    sr = SR
    sig = {'mix': decode_audio(audio, sr=sr)}
    sig['hi'] = _highpass(sig['mix'], sr, p['hi_hz'])
    for part in ('vocals', 'rest'):
        if stem_files and stem_files.get(part):
            sig[part] = decode_audio(stem_files[part], sr=sr)
    out = []
    for an in anchors:
        a = float(an['t'])
        m = {'t': round(a, 3), 'on': an['on'], 'also': list(an.get('also') or [])}
        for name, y in sig.items():
            t, r, lv = _rise_at(y, sr, a, p)
            m[f'{name}_rise'] = round(r, 1)
            m[f'{name}_level'] = round(lv, 1)
            m[f'{name}_onset'] = round(t, 4)
            m[f'{name}_sustain'] = round(_sustain_at(y, sr, t, p), 1)
        for part in ('mix', 'vocals'):
            s = (sed or {}).get(part)
            e = _sed_at(s, a, p) if s is not None else None
            for k, v in (e or {}).items():
                m[f'sed_{part}_{k}'] = round(v, 4) if isinstance(v, float) else v
        out.append(m)
    return out


ANCHOR_FEATURES = ['mix_rise', 'hi_rise', 'vocals_rise', 'rest_rise', 'hi_minus_vocals', 'rest_minus_vocals',
                   'hi_level', 'rest_level', 'sed_mix_ratio', 'sed_vocals_ratio', 'sed_mix_logpeak',
                   'sed_vocals_logpeak', 'sed_mix_speech_ratio', 'sed_music', 'on_cut', 'on_picture', 'on_word']


def anchor_features(m):
    """The numbers anchor_answer weighs, in ANCHOR_FEATURES order (a missing stem or model run counts as no rise)."""
    g = lambda k, d=0.0: float(m.get(k, d) if m.get(k) is not None else d)  # noqa: E731
    return [g('mix_rise'), g('hi_rise'), g('vocals_rise'), g('rest_rise'), g('hi_rise') - g('vocals_rise'),
            g('rest_rise') - g('vocals_rise'), max(g('hi_level', -120), -90), max(g('rest_level', -120), -90),
            g('sed_mix_ratio'), g('sed_vocals_ratio'), np.log10(g('sed_mix_peak') + 1e-4),
            np.log10(g('sed_vocals_peak') + 1e-4), g('sed_mix_speech_ratio'), g('sed_mix_music'),
            float(m.get('on') == 'cut'), float(m.get('on') == 'picture'), float(m.get('on') == 'word')]


# A logistic model over ANCHOR_FEATURES, fitted on the 14 references (truth-sound-v2) and the first held-out set
# (T198 2d step 3, tests/t198/sfx2d/anchor_fit.py); frozen before the second held-out set was scored.
ANCHOR_MODEL = {
    'mu': [4.9571, 7.3053, 5.8136, 3.3146, 1.4917, -2.499, -34.5378, -36.4794, 0.5969, 0.5168, -2.9649, -3.1297,
           0.0272, 0.1523, 0.0969, 0.2168, 0.6863],
    'sd': [8.0199, 9.9837, 9.4046, 6.7083, 8.5579, 8.7892, 11.7258, 11.5717, 0.458, 0.4609, 0.5844, 0.546, 0.2576,
           0.225, 0.2958, 0.4121, 0.464],
    'w': [-2.1074, -1.0113, 0.7909, 0.7712, 0.9459, 0.0752, -0.1033, -0.5291, -0.0483, 0.4835, 0.3572, 0.0898,
          -0.4606, -0.0205, -0.1485, 0.5886, 0.421, -0.7491],
}
ANCHOR_DECIDE = {'found_p': 0.99, 'unsure_p': 0.85, 'words': False, 'cuts': True, 'near_s': 0.1,
                 'splice_hi_sustain_db': 8.0}    # a find on a cut whose top band stays up less than this (dB,
                                                 # 5-40 ms after) is "not sure": the click of a splice (T198 2d step
                                                 # 5, chosen on two held-out sets; None: off)


def anchor_p(m, model=None):
    """How likely an added sound starts at this anchor (0-1), from the frozen model."""
    model = model or ANCHOR_MODEL
    if not model:
        return 0.0
    z = (np.asarray(anchor_features(m)) - np.asarray(model['mu'])) / np.asarray(model['sd'])
    return float(1 / (1 + np.exp(-(model['w'][0] + z @ np.asarray(model['w'][1:])))))


def anchor_answer(measures, found=(), settings=None, model=None):
    """The anchored search's answer: (found, not_sure) events at anchors not already found within near_s. An event's
    t is the onset of the signal that rose most there; kind is the model's kind for the part (mix or vocals stem)
    where its effect class rose most; lands_on is the anchor with the offset in ms (negative: the sound is early).
    Word anchors only when settings words=True; cuts unless cuts=False."""
    p = {**ANCHOR_DECIDE, **(settings or {})}
    taken = [float(x['t']) for x in found]
    yes, unsure = [], []
    for m in measures:
        if (m['on'] == 'word' and not p['words']) or (m['on'] == 'cut' and not p['cuts']):
            continue
        pr = m.get('p', anchor_p(m, model))
        if pr < p['unsure_p']:
            continue
        sig = max(('hi', 'rest', 'mix', 'vocals'), key=lambda s: m.get(f'{s}_rise', -99.0))
        t = float(m.get(f'{sig}_onset', m['t']))
        if any(abs(t - u) <= p['near_s'] for u in taken):
            continue
        part = max(('mix', 'vocals'), key=lambda s: m.get(f'sed_{s}_ratio', -9.0))
        x = {'t': round(t, 4), 'by': 'anchor', 'p': round(pr, 3), 'kind': m.get(f'sed_{part}_kind') or 'other',
             'onset_from': sig, 'anchor': {'on': m['on'], 't': m['t'], 'also': m.get('also') or []},
             'lands_on': {m['on']: {'t': m['t'], 'offset_ms': int(round((t - m['t']) * 1000))}, 'nearest': m['on']}}
        splice = (p['splice_hi_sustain_db'] is not None and (m['on'] == 'cut' or 'cut' in (m.get('also') or []))
                  and m.get('hi_sustain', 99.0) < p['splice_hi_sustain_db'])
        if splice:
            x['why'] = 'a click on a cut that does not stay up: the splice itself, or a very short effect'
        (yes if pr >= p['found_p'] and not splice else unsure).append(x)
        taken.append(t)
    return yes, unsure


# --- Devices (T198 2d step 4): what a Look may carry from the found sounds ---------------------------------------
# A device is a kind of effect plus what it lands on (a cut, a picture change, a word or nothing). A wrong device does
# more harm than a missed one (the Look would add an effect the reference never had), so a device needs evidence:
# min_finds finds of that kind on that kind of moment, or one sure find (sure_alone: 'strict' = a rise of sure_jump_db
# on a picture change, or an anchored p of sure_p; 'loose' = that rise anywhere, or that p; None = never alone).
DEVICE_GATE = {'min_finds': 3, 'sure_alone': None, 'sure_jump_db': 30.0, 'sure_p': 0.999}


def _sure(x, g):
    if g['sure_alone'] is None:
        return False
    if x.get('p') is not None and float(x['p']) >= g['sure_p']:
        return True
    j = x.get('jump_db')
    if j is None or float(j) < g['sure_jump_db']:
        return False
    return g['sure_alone'] == 'loose' or bool(x.get('on_picture_event')) or x.get('land') == 'picture'


def look_devices(finds, gate=None):
    """The devices a Look carries from found sounds. finds: [{'kind', 'land' (cut | picture | word | nothing),
    'offset_ms', 'p' or 'jump_db', 'on_picture_event'}]. Returns [{'kind', 'land', 'n', 'offset_ms' (median),
    'why'}] for the devices with enough evidence (DEVICE_GATE)."""
    g = {**DEVICE_GATE, **(gate or {})}
    groups = {}
    for x in finds:
        groups.setdefault((x.get('kind') or 'other', x.get('land') or 'nothing'), []).append(x)
    out = []
    for (kind, land), xs in sorted(groups.items()):
        many = len(xs) >= g['min_finds']
        sure = [x for x in xs if _sure(x, g)]
        if not (many or sure):
            continue
        offs = [int(x['offset_ms']) for x in xs if x.get('offset_ms') is not None]
        out.append({'kind': kind, 'land': land, 'n': len(xs), 'offset_ms': int(np.median(offs)) if offs else None,
                    'why': f'{len(xs)} finds' if many else 'one sure find'})
    return out


# --- Devices by how they sound (T198 2d step 5) -----------------------------------------------------------------
# A Look needs a sound that sounds like the reference's on the same kind of moment, not its name. Finds are grouped by
# their CLAP audio embedding (a 0.6 s window from the onset, on the film-sound separator's effects stem) within each
# kind of moment; a group is a device, the gate counts its finds, and its sound is the library sound nearest the
# group's centre. tau: two sounds group when they are at least as alike as two library sounds of the same kind
# typically are (the median, over the library's edit kinds, of the median CLAP cosine within a kind: 0.461).
#   bar and linkage (step 6): finds group while they are at least bar alike; 'average' merges while two groups' mean
#   cosine reaches it (step 5: bar = tau), 'complete' only while every pair across them does, so no find of a device
#   is less alike than bar to any other. On the effects stem different effects are more alike than two library
#   sounds (they share the room and the onset: median 0.41, 90th percentile 0.59 on the references), so bar is set
#   apart from tau: 0.65 with complete linkage, the best right minus twice wrong at the 3+ gate on four dev sets
#   (tests/t198/sfx2d/step6_devices.py dev), frozen before the fourth blind set.
#   pick (step 6): 'edit' takes the device's sound from the library's edit effects only (library_role), falling back
#   to a voice, crowd or music sting only when none of the edit effects reaches tau and that sound does; 'all' (step
#   5): the whole library.
#   merge (step 7): every-pair grouping can split one repeated effect in two (seen on a reference: switch clicks on
#   cuts as 4 + 3 finds with the same pick). 'devices': devices that passed the gate on their own, land on the same
#   kind of moment and take the same library sound are one device (the gate is unchanged); 'pick' / 'centre': groups
#   merged before the gate when they take the same sound / their centres are at least bar alike (both rejoined
#   different sounds on the dev sets and were not taken); None: never.
#   tonal_music_db (step 7): a tonal find that lands on no cut, picture change or word, with music around it (the
#   music stem's median level over the 2 s around it above this, dBFS; analyse()'s 'music is playing' level), is not
#   counted toward a device: a note in the music, not an added effect. None: counted.
SOUND_DEVICE = {'tau': 0.461, 'bar': 0.65, 'window_s': 0.6, 'linkage': 'complete', 'pick': 'edit', 'merge': 'devices',
                'tonal_music_db': -45.0}

# Which library sounds a device may take (T198 2d step 6), fixed from the library alone: the sound-effect library's
# folders made for edits, the made-for-edits synth sounds, Kenney's interface clicks, and Kenney's other sounds whose
# category is an edit kind (a laser or zap = glitch, a metal impact = hit). Voices, crowds and music stings only when
# a device sounds like one; animals and the rest (doors, engines, slime, force fields) never.
EDIT_EFFECT_FOLDERS = ('02 Cartoon & Comedy', '04 Dings & Sparkles', '06 Real World & DIY',
                       '08 Whooshes & Transitions')
ONLY_IF_ALIKE_FOLDERS = ('01 Crowd Reactions', '05 Voice Exclamations', '07 Music Stings')


def library_role(item):
    """'edit', 'only_if_alike' or None for a library manifest item (see EDIT_EFFECT_FOLDERS)."""
    folder = item.get('folder')
    if folder:
        return 'edit' if folder in EDIT_EFFECT_FOLDERS else 'only_if_alike' if folder in ONLY_IF_ALIKE_FOLDERS else None
    iid = str(item.get('id') or '')
    if iid.startswith('synth/') or item.get('pack') == 'ui-audio':
        return 'edit'
    return 'edit' if kind_of(item.get('category')) in set(EDIT_KINDS) - {'sting', 'whistle'} else None


def cluster_sounds(lands, emb, tau=None, linkage=None):
    """Groups (lists of indices) of sounds that land on the same kind of moment and sound alike, on the cosine of
    unit-length embeddings: merged while the closest two groups reach tau (linkage 'average': their mean cosine;
    'complete': their least alike pair)."""
    tau = SOUND_DEVICE['bar'] if tau is None else tau
    link = linkage or SOUND_DEVICE['linkage']
    emb = np.asarray(emb, np.float64)
    groups = []
    for land in sorted(set(lands)):
        g = [[i] for i, l_ in enumerate(lands) if l_ == land]
        while len(g) > 1:
            best, pair = -2.0, None
            for a in range(len(g)):
                for b in range(a + 1, len(g)):
                    m = emb[g[a]] @ emb[g[b]].T
                    s = float(m.min() if link == 'complete' else m.mean())
                    if s > best:
                        best, pair = s, (a, b)
            if best < tau:
                break
            a, b = pair
            g[a] = g[a] + g[b]
            del g[b]
        groups += g
    return groups


def pick_sound(centre, library_emb, roles=None, tau=None, pick=None):
    """(index, cosine) of the library sound nearest a device's centre: among the edit effects (pick 'edit', roles
    from library_role), unless none reaches tau and an 'only_if_alike' sound does; or the whole library ('all')."""
    tau = SOUND_DEVICE['tau'] if tau is None else tau
    sims = np.asarray(library_emb, np.float64) @ np.asarray(centre, np.float64)
    if (pick or SOUND_DEVICE['pick']) == 'all' or roles is None:
        k = int(np.argmax(sims))
        return k, float(sims[k])
    roles = list(roles)
    edit = np.array([r == 'edit' for r in roles])
    alike = np.array([r == 'only_if_alike' for r in roles])
    if not edit.any():
        return None, None
    k = int(np.argmax(np.where(edit, sims, -2.0)))
    if sims[k] < tau and alike.any():
        j = int(np.argmax(np.where(alike, sims, -2.0)))
        if sims[j] >= tau:
            k = j
    return k, float(sims[k])


def music_db_at(music, t, sr=SR, half_s=1.0):
    """The music stem's median level (dBFS, HOP steps) over the half_s either side of t; music is the decoded stem."""
    seg = np.asarray(music)[max(0, int((t - half_s) * sr)):max(0, int((t + half_s) * sr))]
    return float(np.median(envelope_db(seg, sr=sr))) if len(seg) >= 1024 else -120.0


def counts_toward_device(x, settings=None):
    """False for a tonal find landing on nothing with music around it (x['music_db'] over tonal_music_db)."""
    p = {**SOUND_DEVICE, **(settings or {})}
    lim = p.get('tonal_music_db')
    return not (lim is not None and x.get('by') == 'tonal' and (x.get('land') or 'nothing') == 'nothing'
                and x.get('music_db') is not None and float(x['music_db']) > lim)


def sound_devices(finds, emb, library_emb, library_ids, tau=None, gate=None, roles=None, settings=None):
    """A Look's sound effect devices from found sounds: finds [{'land', 'offset_ms', 'by', 'music_db'}], emb their
    embeddings (one row each), library_emb / library_ids the library's, roles each library sound's library_role.
    Returns [{'land', 'n', 'offset_ms', 'members' (indices into finds), 'sfx', 'sfx_sim', 'centre', 'alike'}] for the
    groups that pass the gate (DEVICE_GATE's min_finds; sure_alone is not used here); alike is the least alike pair of
    the device's finds. Finds that don't count (counts_toward_device) are left out first; groups are merged (merge)
    before the gate."""
    g = {**DEVICE_GATE, **(gate or {})}
    p = {**SOUND_DEVICE, **(settings or {})}
    if tau is not None:
        p['bar'] = tau
    keep = [i for i, x in enumerate(finds) if counts_toward_device(x, p)]
    if not keep:
        return []
    emb = np.asarray(emb, np.float64)
    groups = []
    for members in cluster_sounds([finds[i].get('land') or 'nothing' for i in keep], emb[keep], p['bar'],
                                  p['linkage']):
        members = [keep[i] for i in members]
        c = emb[members].mean(0)
        c = c / (np.linalg.norm(c) + 1e-9)
        k, sim = pick_sound(c, library_emb, roles, p['tau'], p['pick'])
        groups.append({'members': members, 'land': finds[members[0]].get('land') or 'nothing', 'k': k, 'c': c})
    merged = True
    while merged and p.get('merge') in ('pick', 'centre'):
        merged = False
        for a in range(len(groups)):
            for b in range(a + 1, len(groups)):
                x, y = groups[a], groups[b]
                if x['land'] != y['land']:
                    continue
                same = (x['k'] is not None and x['k'] == y['k']) if p['merge'] == 'pick' else                     float(x['c'] @ y['c']) >= p['bar']
                if same:
                    members = x['members'] + y['members']
                    c = emb[members].mean(0)
                    c = c / (np.linalg.norm(c) + 1e-9)
                    k, _ = pick_sound(c, library_emb, roles, p['tau'], p['pick'])
                    groups[a] = {'members': members, 'land': x['land'], 'k': k, 'c': c}
                    del groups[b]
                    merged = True
                    break
            if merged:
                break
    out = []
    for grp in groups:
        members = grp['members']
        if len(members) < g['min_finds'] or grp['k'] is None:
            continue
        k, sim = pick_sound(grp['c'], library_emb, roles, p['tau'], p['pick'])
        offs = [int(finds[i]['offset_ms']) for i in members if finds[i].get('offset_ms') is not None]
        pair = emb[members] @ emb[members].T
        out.append({'land': grp['land'], 'n': len(members),
                    'offset_ms': int(np.median(offs)) if offs else None, 'members': members,
                    'sfx': f'sfx:{library_ids[k]}', 'sfx_sim': round(sim, 3), 'centre': grp['c'],
                    'alike': round(float(pair.min()), 3)})
    if p.get('merge') == 'devices':             # devices that passed the gate on their own, same sound, same moment
        merged_out = []
        for d in out:
            twin = next((m for m in merged_out if m['land'] == d['land'] and m['sfx'] == d['sfx']), None)
            if twin is None:
                merged_out.append(d)
                continue
            members = twin['members'] + d['members']
            offs = [int(finds[i]['offset_ms']) for i in members if finds[i].get('offset_ms') is not None]
            c = emb[members].mean(0)
            twin.update({'members': members, 'n': len(members), 'offset_ms': int(np.median(offs)) if offs else None,
                         'centre': c / (np.linalg.norm(c) + 1e-9), 'alike': round(float((emb[members] @
                                                                                         emb[members].T).min()), 3),
                         'sfx_sim': round(float(np.asarray(library_emb, np.float64)[library_ids.index(d['sfx'][4:])]
                                                @ (c / (np.linalg.norm(c) + 1e-9))), 3)})
        out = merged_out
    return out


# --- Devices in Learn (T198 2d step 6): an importer setting, off by default ------------------------------------
# With SOUND_DEVICES_ON (or options {'sound_devices': true} to learned_sound.analyse), Learn's sound step also runs
# the step-5 detector and writes the devices into the Look's sound profile (effects.devices): method 1's finds (the
# Demucs residue) plus the cut search on the film-sound separator's stems (DBS-TIGER-DnR) with the splice rule, each
# find embedded with CLAP on the separator's effects stem, grouped by sound within each kind of moment (cut, picture
# change, word, nothing; sound_devices), the gate (3+ finds), and the library sound nearest each device among the
# edit effects. The models (DnR 4 MB, the PANNs sound-event model 312 MB) come on first use like the others.
SOUND_DEVICES_ON = False
# The cut search's model on the DnR stems: fitted like ANCHOR_MODEL on the references and the first held-out set
# (tests/t198/sfx2d/anchor_fit.py --variant=dnr), frozen before the second, third and fourth held-out sets were scored
ANCHOR_MODEL_DNR = {
    'mu': [4.9571, 7.3053, 6.4372, 4.5149, 0.8681, -1.9223, -34.5378, -61.174, 0.5969, 0.5168, -2.9649, -3.1297, 0.0272, 0.1523, 0.0969, 0.2168, 0.6863],
    'sd': [8.0199, 9.9837, 10.5698, 8.3144, 9.3022, 10.0405, 11.7258, 19.7126, 0.458, 0.4609, 0.5844, 0.546, 0.2576, 0.225, 0.2958, 0.4121, 0.464],
    'w': [-2.4053, -0.9703, 0.7395, 0.7933, 1.1303, -0.1078, 0.1008, -0.5276, 0.3569, 0.2136, 0.4044, 0.1704, -0.4467, 0.1052, 0.012, 0.3522, 0.3815, -0.5633],
}
ANCHOR_DECIDE_DNR = {'found_p': 0.995}
DEVICE_LAND_S = 0.25          # a find lands on the nearest cut or picture change this close (a picture change within
                              # 30 ms of a cut is that cut), else the nearest word onset, else nothing


def device_land(t, cuts=(), pictures=(), words=(), within_s=DEVICE_LAND_S):
    """(land, offset_ms) of a sound at t, as the devices were scored: 'cut' | 'picture' | 'word' | 'nothing'."""
    best = None
    for on, times in (('cut', cuts), ('picture', pictures)):
        for u in times:
            if abs(t - u) <= within_s and (best is None or abs(t - u) < abs(best[1])):
                best = (on, t - u)
    if best and best[0] == 'picture':
        u = t - best[1]
        c = [x for x in cuts if abs(x - u) <= 0.03]
        if c:
            best = ('cut', t - min(c, key=lambda x: abs(x - u)))
    if best is None:
        for u in words:
            if abs(t - u) <= within_s and (best is None or abs(t - u) < abs(best[1])):
                best = ('word', t - u)
    return (best[0], int(round(best[1] * 1000))) if best else ('nothing', None)


def device_pictures(report):
    """The picture changes of an importer report a device may land on (what style_import hands gate_sfx, cuts apart):
    transitions, zoom punches, titles, labels and text pops arriving, overlays arriving and leaving."""
    ov = [o for o in (report.get('overlays') or {}).get('events') or [] if o.get('conf', 0) >= 0.5]
    cuts = {round(float(c['t'] if isinstance(c, dict) else c), 3) for c in report.get('cuts') or []}
    t = ([g.get('start', g['t']) for g in report.get('transitions') or [] if g.get('t') is not None]
         + [z['t'] for z in report.get('zooms') or [] if z.get('kind') in ('punch_in', 'punch_out')]
         + [e['t'] for e in report.get('text_events') or [] if e.get('role') in ('title', 'label', 'text_pop')]
         + [o['t'] for o in ov] + [o['end'] for o in ov if o.get('end') is not None])
    return sorted({round(float(x), 3) for x in t} - cuts)


def _device_library(root):
    """(items, embeddings or the cache key when they still have to be made, roles) of the library sounds a device may
    take: every CC0 library sound of 3.5 s or less; its CLAP window (window_s from its onset) is kept in
    <cache>/sfx-devices-library.npz."""
    import hashlib
    import json as _json
    items = []
    for m in LIBRARY_MANIFESTS:
        f = root / 'assets' / 'manifest' / f'{m}.json'
        if f.exists():
            items += [i for i in _json.loads(f.read_text(encoding='utf-8')).get('items') or []
                      if (root / i['file']).exists() and i.get('duration_s', 9) <= 3.5]
    items.sort(key=lambda i: i['id'])
    key = hashlib.sha256(('|'.join(i['id'] for i in items) + f"|{SOUND_DEVICE['window_s']}").encode()).hexdigest()
    cache = root / 'cache' / 'sfx-devices-library.npz'
    if cache.exists():
        d = np.load(cache, allow_pickle=False)
        if str(d['key']) == key:
            return items, d['emb'], [library_role(i) for i in items]
    return items, key, [library_role(i) for i in items]


def _work_name(path):
    import hashlib
    p = Path(path)
    st = p.stat()
    return hashlib.sha256(f'{p.resolve()}|{st.st_size}|{st.st_mtime_ns}'.encode()).hexdigest()[:24]


def find_devices(video, report, demucs_files, method1_events, root=None, log=None, run_worker=None):
    """The sound-effect devices of a reference video (step 5's detector, step 6's devices). report: the importer's
    report (cuts, picture changes, words); demucs_files: its Demucs stems (the vocals go to the sound-event model);
    method1_events: analyse()'s found sound effects. Returns {'devices': [...], 'finds': [...], 'checked', 'method'};
    each device: sfx (a library reference), file (relative to the install), lands_on {kind, offset_ms} (offset: the
    finds' median, negative = early), finds, at_s, alike (its least alike pair), pick_cosine."""
    import letitedit.timeline.made as made
    import letitedit.core.model_fetch as model_fetch
    import hashlib
    import json as _json
    from letitedit.looks import sound_identity
    if root is None:
        from letitedit.core import paths as _paths
        root = _paths.install_root()
    root = Path(root)
    work = root / 'cache' / 'sfx-devices' / _work_name(video)
    work.mkdir(parents=True, exist_ok=True)
    run_worker = run_worker or _run_devices_worker
    dnr_dir = model_fetch.ensure('dbs-tiger-dnr')                          # first use: 4 MB
    sed_file = model_fetch.ensure('panns-cnn14-sed') / 'Cnn14_DecisionLevelMax_mAP=0.385.pth'     # 312 MB
    model_fetch.ensure('clap-htsat-unfused')
    dnr_out = work / 'dnr'
    steps = [{'op': 'dnr', 'code_dir': str(dnr_dir / 'code'), 'weights_dir': str(dnr_dir / 'weights'), 'in': str(video),
              'out_dir': str(dnr_out)},
             {'op': 'sed', 'model_file': str(sed_file),
              'jobs': [{'in': str(video), 'out': str(work / 'sed-mix.npz')},
                       {'in': str(demucs_files['vocals']), 'out': str(work / 'sed-vocals.npz')}]}]
    names_key = hashlib.sha256(_json.dumps(sound_identity.prompts()).encode()).hexdigest()[:16]
    names_file = root / 'cache' / f'sfx-names-{names_key}.npy'
    if not names_file.exists():
        steps.append({'op': 'clap_text', 'hf_home': str(root / 'models/hf'),
                      'texts': sound_identity.prompts(), 'out': str(names_file)})
    items, lib, roles = _device_library(root)
    if isinstance(lib, str):                                       # first use: the library's windows too
        steps.append({'op': 'clap', 'hf_home': str(root / 'models' / 'hf'), 'jobs': [
            {'audio': str(root / i['file']),
             'windows': [[float(i.get('onset_s') or 0.0), float(i.get('onset_s') or 0.0) + SOUND_DEVICE['window_s']]],
             'out': str(work / 'library' / f'{k:04d}.npy')} for k, i in enumerate(items)]})
    took = [run_worker(steps, made.ffmpeg_exe(), work, log)]
    if isinstance(lib, str):
        emb = np.stack([np.load(work / 'library' / f'{k:04d}.npy')[0] for k in range(len(items))])
        np.savez(root / 'cache' / 'sfx-devices-library.npz', key=lib, emb=emb)
        lib = emb
    stems = {'vocals': str(dnr_out / 'speech.wav'), 'drums': str(dnr_out / 'sfx.wav'),
             'other': str(dnr_out / 'music.wav'), 'rest': str(dnr_out / 'sfx.wav')}
    sed = {}
    for part in ('mix', 'vocals'):
        d = np.load(work / f'sed-{part}.npz')
        sed[part] = {'times': d['times'], 'probs': d['probs'].astype(np.float32), 'classes': list(d['classes'])}
    cuts = [float(c['t'] if isinstance(c, dict) else c) for c in report.get('cuts') or []]
    pictures = device_pictures(report)
    words = [float(w['s']) for w in report.get('words') or [] if isinstance(w, dict) and w.get('s') is not None]
    measures = anchor_measures(str(video), stems, sed, anchor_list(cuts, pictures, words))
    found = list(method1_events)
    yes, unsure = anchor_answer(measures, found=found, settings=ANCHOR_DECIDE_DNR, model=ANCHOR_MODEL_DNR)
    finds = []
    music = decode_audio(stems['other'])
    for x in found + yes:
        land, off = device_land(float(x['t']), cuts, pictures, words)
        finds.append({'t': round(float(x['t']), 4), 'by': x.get('by') or 'residue', 'land': land, 'offset_ms': off,
                      'music_db': round(music_db_at(music, float(x['t'])), 1)})
    devices, omitted = [], []
    if finds:
        f_out = work / 'finds.npy'
        if f_out.exists():
            f_out.unlink()
        names_out = work / 'find-names.npy'
        took.append(run_worker([{'op': 'clap', 'hf_home': str(root / 'models' / 'hf'), 'jobs': [
            {'audio': stems['drums'], 'windows': [[x['t'] + start, x['t'] + end] for x in finds
                                                 for start, end in sound_identity.SLICES],
             'out': str(f_out)}]},
            {'op': 'panns_names', 'model_file': str(sed_file), 'jobs': [
                {'audio': stems['drums'], 'windows': [[x['t'], x['t'] + 1.2] for x in finds],
                 'out': str(names_out)}]}], made.ffmpeg_exe(), work, log))
        emb = np.load(f_out).reshape(len(finds), len(sound_identity.SLICES), -1)
        import letitedit.core.render_lock as render_lock
        with render_lock.slot('learn sound audibility'):
            measurements = sound_identity.library_measurements(items, root, decode_audio, SR,
                                                               root / 'cache/sfx-audibility.json')
        named, omitted = sound_identity.named_devices(
            finds, emb, np.load(names_out), sound_identity.prototypes(np.load(names_file)), items, lib,
            measurements, cluster_sounds, min_finds=DEVICE_GATE['min_finds'])
        ids = [i['id'] for i in items]
        for d in named:
            item = items[ids.index(d['sfx'][4:])]
            devices.append({'sfx': d['sfx'], 'file': item['file'], 'category': item.get('category'),
                            'license': item.get('licence') or 'CC0-1.0',
                            'lands_on': {'kind': d['land'], 'offset_ms': d['offset_ms']}, 'finds': d['n'],
                            'at_s': d['at_s'], 'alike': d['alike'], 'kind': d['kind'], 'layers': d['layers'],
                            'audibility': d['audibility'], 'name_evidence': d['name_evidence'],
                            'pick_cosine': d['sfx_sim']})
    return {'devices': devices, 'finds': finds,
            'checked': {'anchors': len(measures), 'method1': len(found), 'cut_search': len(yes),
                        'not_sure': len(unsure), 'settings': dict(SOUND_DEVICE), 'gate': dict(DEVICE_GATE),
                        'took': took, 'omitted': omitted, 'naming_policy': dict(sound_identity.POLICY)},
            'method': ('Demucs residue plus the cut search on DBS-TIGER-DnR stems with the splice rule; '
                       'finds grouped by named sound and target kind (every pair at least bar alike); a '
                       f"device needs {DEVICE_GATE['min_finds']}+ named finds; CLAP text names corroborated by "
                       'AudioSet, separate named layers, audible same-kind library picks, targets within 0.125 s')}


def _run_devices_worker(steps, ffmpeg, work, log=None):
    """One run of bridge/sfx_devices_worker.py in the models environment, in the PC's model slot (the render lock
    first, then the GPU turn), below normal priority, 4 threads."""
    import json as _json
    import letitedit.core.first_use as first_use
    import letitedit.sound.model_tools as model_tools
    import letitedit.core.render_lock as render_lock
    first_use.need_for_python(model_tools.MODELS_PYTHON, [], feature='sound devices')
    job = work / 'job.json'
    job.write_text(_json.dumps({'ffmpeg': str(ffmpeg), 'steps': steps}), encoding='utf-8')
    worker = Path(__file__).resolve().parents[2] / 'sfx_devices_worker.py'
    env = {**os.environ, 'OMP_NUM_THREADS': '4', 'MKL_NUM_THREADS': '4'}
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | (0x00004000 if os.name == 'nt' else 0)
    with render_lock.model_slot('sound devices'):
        r = subprocess.run([str(model_tools.MODELS_PYTHON), '-I', str(worker), str(job)], capture_output=True,
                           text=True, env=env, stdin=subprocess.DEVNULL, creationflags=flags)
    if r.returncode:
        raise RuntimeError(f'sound devices worker: {(r.stderr or r.stdout)[-400:]}')
    line = (r.stdout.strip().splitlines() or ['{}'])[-1]
    try:
        return _json.loads(line)
    except ValueError:
        return {'output': line[-200:]}
