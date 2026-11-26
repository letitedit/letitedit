"""Sustained narrow tones in sound: howls, whines, feedback, whistle-like or theremin-like leads.

    scan_file(path, start_s=None, end_s=None)  -> {'events': [...], 'seconds_flagged', 'share', 'duration_s', ...}
    scan(samples, sr)                          -> the same from a mono float array
    summary_line(result)                       -> one plain sentence, or '' when nothing was found

How it decides (the howling-detection criteria of the acoustic-feedback literature: van Waterschoot and Moonen,
"Fifty years of acoustic feedback control", Proc. IEEE 2011, and the PNPR / PHPR / persistence tests built on them):
  - a tone is a spectral peak at least PNPR_DB above the average power of the bins around it (15 dB is the figure
    common reimplementations use; 12 dB the lowest published test setting);
  - it has almost no harmonics: the peak stands PHPR_DB above the power at twice and three times its frequency. A
    feedback howl is a single near-sinusoid; a sung, bowed, blown or plucked note carries partials a few dB to ~15 dB
    under its peak, so ordinary notes stay under this test (measured on speech and on the library, tests/t161);
  - it persists: the peak stays within a glide of at most GLIDE of the last frame, for MIN_S or longer (a howl builds
    over several analysis windows; a single bell or a blip is shorter).
Measurements are not listening. A flagged stretch may be the sound the video wants (a theremin lead, a whistle).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401 - children start without a console window

SR = 22050
N = 4096            # analysis window: 0.19 s, bins of 5.4 Hz
HOP = 1024          # 46 ms
LOW_HZ, HIGH_HZ = 300.0, 4000.0
PNPR_DB = 20.0      # peak against the average of its neighbours (published setups: 12 to 15 dB; speech holds reach 18)
PHPR_DB = 20.0      # peak against its 2nd and 3rd harmonics
GLIDE = 0.05        # at most 5% change of pitch between frames
MIN_S = 0.4         # shortest stretch reported
GAP_S = 0.15        # a stretch survives this much interruption
SILENCE_DB = -60.0  # frames with less energy than this (dBFS, whole window) are ignored
STRONG_DB = 25.0    # a tone counts as a howl in a mix when it is this far above its neighbours and its harmonics
LONG_S = 2.0        # a strong tone held this long is a finding (shorter ones are reported, not counted)
HOWL_SONG_S = 6.0   # a song with this many seconds of long, very pure tones is hidden from the music search


def _ffmpeg():
    try:
        import letitedit.review.checks as checks
        return str(checks.FFMPEG)
    except Exception:  # noqa: BLE001
        return 'ffmpeg'


def load_mono(path, start_s=None, end_s=None, sr=SR):
    cmd = [_ffmpeg(), '-v', 'error', '-nostdin']
    if start_s:
        cmd += ['-ss', f'{float(start_s):.3f}']
    if end_s is not None:
        cmd += ['-to', f'{float(end_s):.3f}'] if not start_s else ['-t', f'{float(end_s) - float(start_s):.3f}']
    cmd += ['-i', str(path), '-vn', '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-']
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(out, np.float32)


def _frames(x, sr):
    win = np.hanning(N).astype(np.float32)
    count = max(0, (len(x) - N) // HOP + 1)
    lo, hi = int(LOW_HZ * N / sr), int(HIGH_HZ * N / sr)
    for i in range(count):
        seg = x[i * HOP:i * HOP + N]
        power = np.abs(np.fft.rfft(seg * win)) ** 2 + 1e-12
        yield i, power, lo, hi, float(np.mean(seg * seg))


def frame_tone(power, lo, hi, sr):
    """(frequency, pnpr_db, phpr_db) of the strongest peak in the band, or None."""
    k = lo + int(np.argmax(power[lo:hi]))
    a, b = max(0, k - 40), min(len(power), k + 41)
    near = np.concatenate([power[a:max(a, k - 4)], power[k + 5:b]])
    if not len(near):
        return None
    pnpr = 10 * np.log10(power[k] / np.mean(near))
    worst = 0.0
    for mult in (2, 3):
        h = k * mult
        if h + 3 < len(power):
            worst = max(worst, float(np.max(power[h - 2:h + 3])))
    phpr = 10 * np.log10(power[k] / worst) if worst > 0 else 99.0
    return k * sr / N, float(pnpr), float(phpr)


def scan(x, sr=SR, pnpr_db=PNPR_DB, phpr_db=PHPR_DB, min_s=MIN_S):
    x = np.asarray(x, np.float32)
    duration = len(x) / sr
    runs, cur = [], None            # a run: [first_frame, last_frame, freq_list, pnpr_list, phpr_list, level_list]
    for i, power, lo, hi, energy in _frames(x, sr):
        level_db = 10 * np.log10(energy + 1e-12)
        tone = frame_tone(power, lo, hi, sr) if level_db > SILENCE_DB else None
        ok = tone is not None and tone[1] >= pnpr_db and tone[2] >= phpr_db
        if ok and cur is not None and i - cur[1] <= int(GAP_S * sr / HOP) + 1 \
                and abs(tone[0] - cur[2][-1]) / cur[2][-1] <= GLIDE * (1 + (i - cur[1])):
            cur[1] = i
            cur[2].append(tone[0]); cur[3].append(tone[1]); cur[4].append(tone[2]); cur[5].append(level_db)
        elif ok:
            if cur is not None:
                runs.append(cur)
            cur = [i, i, [tone[0]], [tone[1]], [tone[2]], [level_db]]
    if cur is not None:
        runs.append(cur)
    events = []
    for first, last, freqs, pnprs, phprs, levels in runs:
        start, end = (first * HOP + N / 2 - HOP / 2) / sr, (last * HOP + N / 2 + HOP / 2) / sr
        if end - start >= min_s:
            events.append({'start_s': round(start, 2), 'end_s': round(end, 2), 'hz': int(np.median(freqs)),
                           'pnpr_db': round(float(np.median(pnprs)), 1), 'phpr_db': round(float(np.median(phprs)), 1),
                           'level_dbfs': round(float(np.median(levels)), 1)})
    flagged = sum(e['end_s'] - e['start_s'] for e in events)
    return {'duration_s': round(duration, 2), 'events': events, 'seconds_flagged': round(flagged, 2),
            'share': round(flagged / duration, 4) if duration else 0.0,
            'criteria': {'pnpr_db': pnpr_db, 'phpr_db': phpr_db, 'min_s': min_s}}


def scan_file(path, start_s=None, end_s=None, **kw):
    result = scan(load_mono(path, start_s, end_s), SR, **kw)
    if start_s:
        for e in result['events']:
            e['start_s'] = round(e['start_s'] + float(start_s), 2)
            e['end_s'] = round(e['end_s'] + float(start_s), 2)
    return result


def scan_script_music(script):
    """The parts of songs a project uses (tracks named Music*), scanned at their own in and out points:
    {'events': [...with the clip id], 'seconds_flagged', 'seconds', 'share', 'flagged'} - before anything is rendered."""
    import re
    events, seconds = [], 0.0
    for track in script.get('tracks', []):
        if not re.match(r'(?i)music', track.get('name') or ''):
            continue
        for item in track.get('items', []):
            clip = item.get('clip')
            if not clip or not Path(str(clip)).is_file():
                continue
            a = float(item.get('in') or 0)
            b = float(item['out']) if item.get('out') is not None else None
            result = scan_file(clip, a or None, b)
            seconds += result['duration_s']
            for e in result['events']:
                events.append({**e, 'clip': item.get('id'), 'song_start_s': e['start_s'], 'song_end_s': e['end_s']})
    flagged_s = sum(e['end_s'] - e['start_s'] for e in events)
    out = {'events': events, 'seconds_flagged': round(flagged_s, 2), 'duration_s': round(seconds, 2),
           'share': round(flagged_s / seconds, 4) if seconds else 0.0}
    out['flagged'] = flagged(out)
    return out


def strong(result):
    """The events a listener hears as a howl or whistle: narrow (PNPR) and pure (PHPR) by STRONG_DB or more."""
    return [e for e in result.get('events') or [] if e['pnpr_db'] >= STRONG_DB and e['phpr_db'] >= STRONG_DB]


def held(result):
    """The strong tones held LONG_S or more: what a listener hears as a whistle or howl, not a melody's notes."""
    return [e for e in strong(result) if e['end_s'] - e['start_s'] >= LONG_S]


def flagged(result):
    """True when a strong tone is held LONG_S (2 s) or more: the one definition of a whistle-like tone, for the export's
    pre-check, the mix check, the review and written music. Shorter strong tones (a pure lead's notes) are reported in
    the events and the summary line, never counted."""
    return bool(held(result))


def howl_seconds(result):
    """For a whole song: seconds of very narrow, very pure tones of 2 s or more in the 400-3000 Hz range where hearing is
    most sensitive (PNPR and PHPR of 30 dB or more). A song with HOWL_SONG_S of it is hidden from the music search."""
    return round(sum(e['end_s'] - e['start_s'] for e in result.get('events') or []
                     if 400 <= e['hz'] <= 3000 and e['pnpr_db'] >= 30 and e['phpr_db'] >= 30
                     and e['end_s'] - e['start_s'] >= 2.0), 2)


def summary_line(result, label='the sound'):
    """N tone(s), how long in all, and the first four with their times and pitch, those held LONG_S or more first."""
    events = strong(result) or (result.get('events') or [])
    events = sorted(events, key=lambda e: (e['end_s'] - e['start_s'] < LONG_S, e['start_s']))
    if not events:
        return ''
    seconds = sum(e['end_s'] - e['start_s'] for e in events)
    duration = result.get('duration_s') or 0
    first = ', '.join(f"{e['start_s']:g}-{e['end_s']:g} s (~{e['hz']} Hz)" for e in events[:4])
    return (f"{len(events)} sustained narrow tone(s) in {label}, whistle- or howl-like ({seconds:.1f} s"
            + (f", {seconds / duration:.0%}" if duration else '') + f"): {first}" + (' ...' if len(events) > 4 else ''))


# ---------------------------------------------------------------------------- the music library

_SIDECAR = {}


def library_facts(root):
    """{casefolded relative path: {share, seconds_flagged, longest_s, events, flagged}} from <root>/tonal.json (written by
    scan_library); {} when the library has not been scanned."""
    import json
    path = Path(root) / 'tonal.json'
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return {}
    cached = _SIDECAR.get(str(path))
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}
    facts = {k.replace(chr(92), '/').casefold(): v for k, v in (data.get('songs') or {}).items()}
    _SIDECAR[str(path)] = (stamp, facts)
    return facts


def song_entry(result, size=None):
    events = result.get('events') or []
    longest = max((e['end_s'] - e['start_s'] for e in events), default=0.0)
    howl = howl_seconds(result)
    return {'size': size, 'duration_s': result.get('duration_s'), 'share': result.get('share'),
            'seconds_flagged': result.get('seconds_flagged'), 'longest_s': round(longest, 2), 'events': len(events),
            'howl_seconds': howl, 'flagged': howl >= HOWL_SONG_S}


def scan_library(root, out=None, progress=None):
    """Scan every song under root once and store the result beside them (tonal.json); a song already scanned with the
    same size and the same criteria is kept. Run at below-normal priority and never alongside a render."""
    import json
    root = Path(root)
    out = Path(out) if out else root / 'tonal.json'
    old = {}
    try:
        old = json.loads(out.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        pass
    criteria = {'pnpr_db': PNPR_DB, 'phpr_db': PHPR_DB, 'min_s': MIN_S, 'low_hz': LOW_HZ, 'howl_song_s': HOWL_SONG_S}
    keep = old.get('songs', {}) if old.get('criteria') == criteria else {}
    songs = {}
    files = sorted(f for f in root.rglob('*') if f.suffix.lower() in ('.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.opus'))
    for n, f in enumerate(files):
        rel = f.relative_to(root).as_posix()
        size = f.stat().st_size
        if rel in keep and keep[rel].get('size') == size:
            songs[rel] = keep[rel]
            continue
        try:
            songs[rel] = song_entry(scan_file(f), size)
        except Exception as error:  # noqa: BLE001 - an unreadable song is left out of the list, not guessed
            songs[rel] = {'size': size, 'error': str(error)[:120]}
        if progress:
            progress(n, len(files), rel)
    data = {'about': 'Sustained narrow tones (howl, whine, whistle-like leads) per song: tonal_check.py', 'criteria': criteria,
            'songs': songs}
    tmp = out.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, indent=1), encoding='utf-8')
    tmp.replace(out)
    return data
