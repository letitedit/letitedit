"""Perception: what is in a source file besides talking, so the editor (an LLM) can make creative choices.

    sounds(path)    non-speech sound events: bangs / clanks / thuds / clicks, repeated hits (hammering), steady loud
                    noise (machine?), hums / whines / beeps, music-like sound, quiet stretches; room tone and talking
                    level (voice detection from music.voice_profile keeps speech out)
    picture(path)   per second: steady / slight drift / pan / tilt / shaky handheld / fast whip; blurry, dark and
                    blown-out spans; cuts and big scene changes; where the motion (the action) is in steady shots
    music(path)     tempo (bpm), beats and downbeats (letitedit_creator.beats), energy sections (intro/build/peak/outro)
    photo(path)     size, orientation, date taken, camera (HEIC via pillow-heif)
    text(path)      the start of a small text file
    kind(path)      video | image | audio | text | other | system

Every analysis is cached by file content (size + hash of the first 2 MB, like footage notes) under the cache folder
(sounds/, motion/, beats/), so a copy of a clip shares it. analyze_many() runs them for many files at once.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path

import numpy as np

CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache')))
APP = Path(os.environ.get('LETITEDIT_APP', (_SAI_ROOT + '\\app')))
FFMPEG, FFPROBE = APP / 'ffmpeg.exe', APP / 'ffprobe.exe'
CREATOR = _paths.CODE_ROOT / 'creator'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

VIDEO = {'.mov', '.mp4', '.m4v', '.mkv', '.avi', '.mts', '.m2ts', '.webm', '.mxf', '.wmv', '.3gp'}
IMAGE = {'.png', '.jpg', '.jpeg', '.heic', '.heif', '.webp', '.bmp', '.tif', '.tiff', '.gif', '.avif', '.dng'}
AUDIO = {'.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.aiff', '.aif', '.wma'}
TEXT = {'.txt', '.md', '.markdown', '.srt', '.vtt', '.csv', '.tsv', '.json', '.xml', '.yaml', '.yml', '.log', '.ass',
        '.ssa', '.ini', '.cfg', '.toml', '.html', '.htm', '.rtf', '.edl', '.cue', '.lrc', '.sbv', '.nfo'}
SYSTEM = {'desktop.ini', 'thumbs.db', '.ds_store', 'icon\r'}
VERSIONS = {'sounds': 1, 'motion': 2, 'beats': 2}     # part of each cache key: bump when an analysis changes


# ------------------------------------------------------------------ files and caching

def kind(path):
    p = Path(path)
    name, ext = p.name.lower(), p.suffix.lower()
    if name in SYSTEM or name.startswith('~$') or name.startswith('._'):
        return 'system'
    if ext in VIDEO:
        return 'video'
    if ext in IMAGE:
        return 'image'
    if ext in AUDIO:
        return 'audio'
    if ext in TEXT or _looks_like_text(p):
        return 'text'
    return 'other'


def _looks_like_text(p):
    try:
        if p.stat().st_size > 512 * 1024:
            return False
        with open(p, 'rb') as fh:
            head = fh.read(4096)
    except OSError:
        return False
    if head.startswith((b'\xff\xfe', b'\xfe\xff')):
        return True                         # UTF-16 with a byte-order mark
    if not head or b'\0' in head:
        return False
    try:
        head.decode('utf-8')
        return True
    except UnicodeDecodeError as e:
        return e.start > len(head) - 4    # cut in the middle of a character


def content_key(path):
    import letitedit.footage.footage_notes as footage_notes
    return footage_notes.key(path)


def _cached(folder, path, compute, refresh=False):
    """compute() once per file content and analysis version; JSON under CACHE/folder."""
    d = CACHE / folder
    f = d / f'{content_key(path)}-v{VERSIONS[folder]}.json'
    if f.exists() and not refresh:
        try:
            with open(f, encoding='utf-8-sig') as fh:
                return json.load(fh)
        except ValueError:
            pass
    value = compute()
    d.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f'{f.stem}.{os.getpid()}.{threading.get_ident()}.tmp')
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(value, fh, separators=(',', ':'))
    for attempt in range(5):
        try:
            os.replace(tmp, f)
            break
        except PermissionError:
            # Windows refuses a rename onto a file another worker is renaming or reading at that moment; the file
            # is keyed by content, so a result already there is this same result
            if f.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
                break
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))
    return value


def is_cached(folder, path):
    try:
        return (CACHE / folder / f'{content_key(path)}-v{VERSIONS[folder]}.json').exists()
    except OSError:
        return False


def clock(s, digits=1):
    """'m:ss.d' (digits=1) or 'm:ss' (digits=0, rounded)."""
    s = round(max(0.0, float(s)), digits)
    m = int(s // 60)
    sec = s - 60 * m
    if digits == 0:
        return f'{m}:{int(round(sec)):02d}'
    return f'{m}:{sec:0{3 + digits}.{digits}f}'


def span(a, b, digits=1):
    return f'{clock(a, digits)}-{clock(b, digits)}'


def size_text(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024


def _decode_audio(path, sr):
    r = subprocess.run([str(FFMPEG), '-v', 'error', '-nostdin', '-i', str(path), '-vn', '-sn', '-dn', '-ac', '1',
                        '-ar', str(sr), '-f', 'f32le', '-'], capture_output=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        # no sound track: nothing to hear (as before); a read or decode that failed: raised, so nothing is cached
        from letitedit.core import media
        if media.audio_streams(path) == 0:
            return np.zeros(0, np.float32)
        raise media.unreadable(path, 'the sound', r.stderr.decode('utf-8', 'replace') if r.stderr else '')
    data = r.stdout[:len(r.stdout) // 4 * 4]
    return np.frombuffer(data, np.float32)


def _runs(mask):
    """[(start, end)) index runs where mask is True."""
    m = np.concatenate([[False], np.asarray(mask, bool), [False]])
    d = np.flatnonzero(np.diff(m.astype(np.int8)))
    return list(zip(d[::2].tolist(), d[1::2].tolist()))


# ------------------------------------------------------------------ sounds

SR, HOP, NFFT = 16000, 160, 512
FR = SR / HOP                       # analysis frames per second (10 ms)


def _a_weight(freqs):
    def ra(f):
        f2 = np.asarray(f, float) ** 2
        return 12194.0 ** 2 * f2 ** 2 / ((f2 + 20.6 ** 2) * np.sqrt((f2 + 107.7 ** 2) * (f2 + 737.9 ** 2)) *
                                         (f2 + 12194.0 ** 2) + 1e-30)
    return (ra(freqs) / ra(1000.0)) ** 2


def audio_features(y):
    """Per 10 ms frame: A-weighted level (dB re full scale, a full-scale sine = -3), spectral flatness and
    tonality (share of the energy around the strongest peak) in 150 Hz-7 kHz, that peak's frequency, centroid."""
    n = max(0, (len(y) - NFFT) // HOP + 1)
    win = np.hanning(NFFT).astype(np.float32)
    norm = 2.0 / (NFFT * float((win ** 2).sum()))
    freqs = np.fft.rfftfreq(NFFT, 1 / SR)
    aw = _a_weight(freqs).astype(np.float32)
    band = (freqs >= 150) & (freqs <= 7000)
    lo = int(np.flatnonzero(band)[0])
    bf = freqs[band]
    out = {k: np.zeros(n, np.float32) for k in ('lvl', 'flat', 'tonal', 'pitch', 'cent')}
    offs = np.arange(NFFT)[None, :]
    for s in range(0, n, 3000):
        e = min(n, s + 3000)
        frames = y[np.arange(s, e)[:, None] * HOP + offs] * win
        S = np.abs(np.fft.rfft(frames, axis=1)) ** 2
        S = S.astype(np.float32) + 1e-12
        SA = S * aw
        tot = SA.sum(1)
        out['lvl'][s:e] = 10 * np.log10(tot * norm + 1e-13)
        B = S[:, band]
        bsum = B.sum(1)
        out['flat'][s:e] = np.exp(np.log(B).mean(1)) / (bsum / B.shape[1])
        k = B.argmax(1)
        rows = np.arange(e - s)
        Bp = np.pad(B, ((0, 0), (2, 2)))
        around = sum(Bp[rows, k + 2 + j] for j in (-2, -1, 0, 1, 2))
        out['tonal'][s:e] = around / bsum
        a, b, c = (np.log(S[rows, np.clip(lo + k + j, 0, S.shape[1] - 1)]) for j in (-1, 0, 1))
        den = a - 2 * b + c
        delta = np.where(np.abs(den) > 1e-9, 0.5 * (a - c) / np.where(np.abs(den) > 1e-9, den, 1), 0)
        out['pitch'][s:e] = bf[k] + np.clip(delta, -0.5, 0.5) * (freqs[1] - freqs[0])
        out['cent'][s:e] = (SA * freqs).sum(1) / tot
    return out


def _roughness(lvl_lin):
    """Modulation depth of the loudness envelope at 8-40 Hz (rattle, grinding, scraping): 0 = smooth, 1 = fully
    modulated."""
    x = np.asarray(lvl_lin, float)
    if x.size < 64:
        return 0.0
    win = np.hanning(64)
    f = np.fft.rfftfreq(64, 1 / FR)
    band = (f >= 8) & (f <= 40)
    vals = []
    for s in range(0, x.size - 63, 32):
        seg = np.sqrt(x[s:s + 64])                  # amplitude envelope
        m = seg.mean()
        if m <= 0:
            continue
        spec = np.abs(np.fft.rfft((seg - m) * win)) * 2 / win.sum() / m
        vals.append(float(np.sqrt((spec[band] ** 2).sum())))
    return float(np.median(vals)) if vals else 0.0


def _tone_name(f, dur):
    ftxt = f'{f / 1000:.1f} kHz' if f >= 1500 else f'{int(round(f, -1))} Hz'
    if dur < 1.5:
        return f'beep ~{ftxt}'
    if f < 400:
        return f'hum ~{ftxt}'
    if f < 1500:
        return f'tone ~{ftxt}'
    return f'whine ~{ftxt}'


def _impact_events(L, cent, percentile_filter, pitch, room, speech_hi, tc, tonal, vmask, events):
    # -- impacts: a sharp rise well above what came just before, that dies away again
    bg = percentile_filter(L, 30, size=41, origin=20, mode='nearest')
    bg = np.concatenate([np.full(5, bg[0]), bg[:-5]])
    rise3 = L - np.concatenate([np.full(3, L[0]), L[:-3]])
    cands = np.flatnonzero((L - bg >= 18) & (rise3 >= 10) & (L >= room + 20))
    hits, last = [], -10**9
    for i in cands:
        p = int(i + np.argmax(L[i:i + 6]))
        if p - last < 15:                                           # same hit (150 ms)
            if hits and L[p] > hits[-1]['db']:
                hits[-1].update(i=p, db=float(L[p]))
            continue
        tail = L[p + 15:p + 30]
        if tail.size and tail.mean() > L[p] - 8:                   # did not die away: a loud sound starting
            continue
        if vmask[p] and (speech_hi is None or L[p] < speech_hi + 4):
            continue                                                # part of the talking
        last = p
        hits.append({'i': p, 'db': float(L[p])})
    for h in hits:
        p = h['i']
        dec = slice(p + 3, p + 20)
        width = int((L[p:p + 12] > L[p] - 10).sum())
        ring = float(np.median(tonal[dec])) if tonal[dec].size else 0
        ring_f = float(np.median(pitch[dec])) if pitch[dec].size else 0
        c = float(cent[p])
        if ring >= 0.35 and ring_f >= 700:
            k = 'clank'
        elif width <= 3 and c >= 2000:
            k = 'click'
        elif c < 700:
            k = 'thud'
        else:
            k = 'bang'
        h.update(t=float(tc[p]), kind=k)
    # repeated hits (hammering, knocking): 4 or more, at most 1.5 s apart
    groups, cur = [], []
    for h in hits:
        if cur and h['t'] - cur[-1]['t'] > 1.5:
            groups.append(cur)
            cur = []
        cur.append(h)
    if cur:
        groups.append(cur)
    for g in groups:
        if len(g) >= 4:
            dur = g[-1]['t'] - g[0]['t']
            events.append({'t0': round(g[0]['t'], 2), 't1': round(g[-1]['t'], 2), 'kind': 'hits', 'n': len(g),
                           'rate': round((len(g) - 1) / dur, 1) if dur > 0 else 0,
                           'db': round(max(x['db'] for x in g), 1), 'over': round(max(x['db'] for x in g) - room, 1)})
        else:
            events += [{'t': round(h['t'], 2), 'kind': h['kind'], 'db': round(h['db'], 1),
                        'over': round(h['db'] - room, 1)} for h in g]
    return events


def _sustained_events(L, Ls, cent, events, flat, median_filter, pitch, room, speech_db, speech_hi, tc, tonal,
        vmask):
    # -- sustained sounds: louder than the room for 1.5 s or more, outside talking (bridged across short talk)
    noisy = median_filter(flat, size=25, mode='nearest') >= 0.25
    cand = (Ls >= room + 12) & (~vmask | (noisy & (Ls >= room + 15)) |
                                (Ls >= (speech_hi + 3 if speech_hi is not None else 1e9)))
    spans = []
    for a, b in _runs(cand):
        if spans:
            pa, pb = spans[-1]
            gap = slice(pb, a)
            gap_voice = vmask[gap].mean() if a > pb else 0
            near = abs(float(np.median(Ls[max(pa, pb - 100):pb])) - float(np.median(Ls[a:a + 100]))) <= 6
            if a - pb <= 40 or (a - pb <= 300 and gap_voice >= 0.6 and near):
                spans[-1] = (pa, b)
                continue
        spans.append((a, b))
    # beeps / tones: a clear, stable pitch above 400 Hz (lower ones are hum, handled with the sustained sounds)
    tonal_runs = []
    tmask = (median_filter(tonal, size=9, mode='nearest') >= 0.7) & (L >= room + 15) & ~vmask
    for a, b in _runs(tmask):
        if b - a < 10:
            continue
        pm = float(np.median(pitch[a:b]))
        if pm < 400 or np.mean(np.abs(pitch[a:b] - pm) <= 0.03 * pm + 10) < 0.8:
            continue
        tonal_runs.append([a, b, pm])
    used_tones = set()
    for a, b in spans:
        if b - a < 150:
            continue
        sel = np.arange(a, b)
        quiet_part = sel[~vmask[a:b]] if (~vmask[a:b]).sum() >= 50 else sel
        level = float(np.median(Ls[quiet_part]))
        ton = float(np.median(tonal[quiet_part]))
        fl = float(np.median(flat[quiet_part]))
        ce = float(np.median(cent[quiet_part]))
        rough = _roughness(10 ** (L[quiet_part] / 10))
        steady = float(np.std(Ls[quiet_part])) <= 3.5
        dur = (b - a) / FR
        # the dominant pitch (quarter-tone bins) and how many different notes there are
        pq = np.round(24 * np.log2(np.maximum(pitch[quiet_part], 20) / 440.0)).astype(int)
        vals, cnt = np.unique(pq, return_counts=True)
        mode_share = float(cnt.max() / cnt.sum())
        pm = float(np.median(pitch[quiet_part][pq == vals[cnt.argmax()]]))
        notes = np.bincount((np.round(pq / 2).astype(int) % 12), minlength=12) / max(1, pq.size)
        varied = int((notes >= 0.06).sum())
        sticky = float(np.mean(pq[1:] == pq[:-1])) if pq.size > 1 else 0.0   # notes held (music) vs hopping
        r = ', rough' if rough >= 0.45 else ''
        st = 'steady ' if steady else ''
        if ton >= 0.4 and varied >= 5 and mode_share < 0.3 and sticky >= 0.6 and dur >= 4:
            desc = 'tonal, changing notes (music?)'
        elif ton >= 0.6 and mode_share >= 0.3:
            desc = _tone_name(pm, dur) + (', steady' if steady else '') + r
            for j, (ta, tb, _) in enumerate(tonal_runs):
                if ta < b and tb > a:
                    used_tones.add(j)
        elif ce < 350:
            desc = st + 'low rumble (engine/wind/handling?)'
        elif fl >= 0.2 or ton < 0.3:
            if rough >= 0.45:
                desc = st + 'noise, rough (machine? grinding/drill/saw)'
            else:
                desc = (st or 'varying ') + 'noise (fan/motor/water/traffic?)'
        elif mode_share >= 0.25:
            desc = st + f'machine-like noise, humming ~{int(round(pm, -1))} Hz' + r
        else:
            desc = st + 'machine-like noise, pitch wandering (grinding/whirring motor?)' + r
        louder = level >= -14 or (speech_db is not None and level >= speech_db + 6)
        loud = louder or level - room >= 20 or (speech_db is not None and level >= speech_db - 3)
        ev = {'t0': round(float(tc[a]), 2), 't1': round(float(tc[b - 1]), 2), 'kind': 'sustained', 'desc': desc,
              'db': round(level, 1), 'over': round(level - room, 1),
              'loud': 'very loud' if louder else 'loud' if loud else '',
              'talk': round(float(vmask[a:b].mean()), 2), 'rough': round(rough, 2), 'tonal': round(ton, 2),
              'flat': round(fl, 3)}
        events.append(ev)
    return tonal_runs, used_tones


def _short_tone_events(L, events, room, tc, tonal_runs, used_tones):
    # short tones (beeps) and tones not inside a sustained span
    beeps = []
    for j, (a, b, pm) in enumerate(tonal_runs):
        if j in used_tones or any(e.get('kind') == 'sustained' and e['t0'] - 0.05 <= tc[a] <= e['t1'] + 0.05
                                  for e in events):
            continue
        beeps.append({'t0': float(tc[a]), 't1': float(tc[b - 1]), 'f': pm, 'db': float(np.max(L[a:b]))})
    i = 0
    while i < len(beeps):
        j = i
        while (j + 1 < len(beeps) and beeps[j + 1]['t0'] - beeps[j]['t1'] <= 1.5 and
               abs(beeps[j + 1]['f'] - beeps[i]['f']) <= 0.06 * beeps[i]['f'] + 20):
            j += 1
        g = beeps[i:j + 1]
        dur = g[0]['t1'] - g[0]['t0']
        name = _tone_name(g[0]['f'], dur)
        db = max(x['db'] for x in g)
        ev = {'t0': round(g[0]['t0'], 2), 't1': round(g[-1]['t1'], 2), 'kind': 'tone', 'desc': name,
              'n': len(g), 'db': round(db, 1), 'over': round(db - room, 1)}
        events.append(ev)
        i = j + 1


def sound_events(feat, voice, duration):
    """Non-speech events from audio_features() and voice spans. Returns the analysis dict (see sounds())."""
    from scipy.ndimage import median_filter, percentile_filter
    L = feat['lvl'].astype(float)
    n = L.size
    res = {'v': VERSIONS['sounds'], 'duration': round(float(duration), 2), 'events': []}
    if n < 10 or float(L.max()) < -90:
        res.update(room_db=-120.0, silent=True)
        return res
    tc = (np.arange(n) * HOP + NFFT / 2) / SR                      # frame centre times
    room = max(-90.0, float(np.percentile(L, 10)))                # digital silence: count from -90
    vmask = np.zeros(n, bool)
    for a, b in voice:
        vmask[max(0, int((a - 0.1) * FR)):max(0, int((b + 0.1) * FR) + 1)] = True
    vmask = vmask[:n]
    speech_db = speech_hi = None
    if vmask.sum() >= 30:
        speech_db, speech_hi = float(np.percentile(L[vmask], 80)), float(np.percentile(L[vmask], 95))
    loud_i = int(np.argmax(L))
    res.update(room_db=round(room, 1), speech_db=None if speech_db is None else round(speech_db, 1),
               loudest_db=round(float(L[loud_i]), 1), loudest_at=round(float(tc[loud_i]), 2),
               speech_s=round(float(sum(b - a for a, b in voice)), 1))
    flat, tonal, pitch, cent = feat['flat'], feat['tonal'], feat['pitch'], feat['cent']
    Ls = median_filter(L, size=51, mode='nearest')
    events = []

    events = _impact_events(L, cent, percentile_filter, pitch, room, speech_hi, tc, tonal, vmask, events)

    tonal_runs, used_tones = _sustained_events(L, Ls, cent, events, flat, median_filter, pitch, room,
        speech_db, speech_hi, tc, tonal, vmask)
    _short_tone_events(L, events, room, tc, tonal_runs, used_tones)

    # -- quiet stretches (only room tone), when the clip has louder parts
    if float(np.median(L)) >= room + 6 or speech_db is not None:
        for a, b in _runs((Ls <= room + 3) & ~vmask):
            if b - a >= 250:
                events.append({'t0': round(float(tc[a]), 2), 't1': round(float(tc[b - 1]), 2), 'kind': 'quiet',
                               'db': round(float(np.median(L[a:b])), 1)})
    if room >= -38:
        res['loud_background'] = True
    events.sort(key=lambda e: e.get('t', e.get('t0', 0)))
    res['events'] = events
    return res


def sounds(path, refresh=False):
    """Non-speech sound analysis of a file (cached by content). Keys: room_db (A-weighted room tone, dB re full
    scale), speech_db (typical talking level), loudest_db / loudest_at, events: [{t | t0,t1, kind, ...}] with kind
    bang | clank | thud | click | hits | sustained | tone | quiet."""
    def compute():
        import letitedit.sound.music as music
        y = _decode_audio(path, SR)
        dur = len(y) / SR
        try:
            voice = music.voice_profile(str(path))['voice'] if dur > 0.5 else []
        except Exception:  # noqa: BLE001
            voice = []
        return sound_events(audio_features(y), voice, dur)
    return _cached('sounds', path, compute, refresh)


def _ev_level(e, room_word=True):
    over = e.get('over')
    if over is None:
        return ''
    return f'{e["db"]:+.0f} dB, +{over:.0f} over room' if room_word else f'+{over:.0f} dB'


def sound_lines(res, limit=80):
    """Compact lines, one per event, for a single-file report. With more than `limit` events, every non-impact
    event is kept and only the loudest single impacts (bangs, clicks...) are listed."""
    if res.get('silent'):
        return ['no sound (silent audio)']
    out = []
    events = res['events']
    dropped = 0
    if len(events) > limit:
        impacts = sorted((e for e in events if 't' in e), key=lambda e: -e['db'])
        others = [e for e in events if 't' not in e]
        keep = impacts[:max(10, limit - len(others))]
        dropped = len(impacts) - len(keep)
        events = sorted(others + keep, key=lambda e: e.get('t', e.get('t0', 0)))
    for e in events:
        k = e['kind']
        if 't' in e:
            loud = 'very loud' if e['db'] >= -12 else 'loud' if e['over'] >= 28 else ''
            out.append(f"{clock(e['t'])} {k} ({', '.join(x for x in (loud, _ev_level(e)) if x)})")
        elif k == 'hits':
            out.append(f"{span(e['t0'], e['t1'])} repeated hits (hammering/knocking?): {e['n']} hits, "
                       f"~{e['rate']:g}/s, loudest {e['db']:+.0f} dB, +{e['over']:.0f} over room")
        elif k == 'sustained':
            talk = ', talking over it' if e['talk'] >= 0.3 else ''
            loud = f"{e['loud']} " if e['loud'] else ''
            out.append(f"{span(e['t0'], e['t1'])} {loud}{e['desc']} ({_ev_level(e)}{talk})")
        elif k == 'tone':
            n = f"{e['n']} x " if e.get('n', 1) > 1 else ''
            when = clock(e['t0']) if e['t1'] - e['t0'] < 1.5 and e.get('n', 1) == 1 else span(e['t0'], e['t1'])
            out.append(f"{when} {n}{e['desc']} ({_ev_level(e)})")
        elif k == 'quiet':
            out.append(f"{span(e['t0'], e['t1'])} quiet (room tone only)")
    if dropped:
        out.append(f'(+{dropped} quieter bangs/clicks/thuds not listed)')
    return out


def sound_header(res):
    if res.get('silent'):
        return 'no sound (silent audio)'
    bits = [f"room tone {res['room_db']:.0f} dB"]
    if res.get('speech_db') is not None:
        bits.append(f"talking ~{res['speech_db']:.0f} dB")
    bits.append(f"loudest {res['loudest_db']:.0f} dB at {clock(res['loudest_at'])}")
    if res.get('loud_background'):
        bits.append('loud background throughout')
    return ', '.join(bits)


SHORT = [('tonal, changing notes (music?)', 'music?'),
         ('machine-like noise, pitch wandering (grinding/whirring motor?)', 'grinding/whirring'),
         ('machine-like noise, humming', 'machine hum'), ('noise, rough (machine? grinding/drill/saw)',
                                                          'rough noise (machine?)'),
         ('noise (fan/motor/water/traffic?)', 'noise'), ('low rumble (engine/wind/handling?)', 'rumble'),
         ('steady ', ''), ('varying ', ''), (', steady', ''), (', rough', '')]


def _short(desc):
    for a, b in SHORT:
        desc = desc.replace(a, b)
    return desc.replace(' rough', '').replace('machine hum', 'hum').strip()


def sound_summary(res, spans_per_kind=3, limit=6):
    """One short phrase for a folder listing: sustained sounds (loudest first, same kinds together), repeated hits,
    impacts (count by kind, loudest), beeps, quiet stretches."""
    if res.get('silent'):
        return 'silent'
    ev = res['events']
    parts = []
    if res.get('loud_background'):
        parts.append('loud background throughout')
    groups = {}
    for e in ev:
        if e['kind'] == 'sustained':
            key = _short(e['desc'])
            groups.setdefault(key, []).append(e)
    ranked = sorted(groups.items(), key=lambda kv: -max(x['over'] for x in kv[1]))
    for key, es in ranked[:3]:
        loud = 'very loud ' if any(x['loud'] == 'very loud' for x in es) else \
            'loud ' if any(x['loud'] for x in es) else ''
        spans_ = ', '.join(span(x['t0'], x['t1'], 0) for x in es[:spans_per_kind])
        parts.append(f"{loud}{key} {spans_}" + (f' +{len(es) - spans_per_kind}' if len(es) > spans_per_kind else ''))
    if len(ranked) > 3:
        n_other = sum(len(es) for _, es in ranked[3:])
        parts.append(f"{n_other} other noise{'s' if n_other > 1 else ''}")
    hits = [e for e in ev if e['kind'] == 'hits']
    if hits:
        parts.append('repeated hits ' + ', '.join(f"{span(e['t0'], e['t1'], 0)} (x{e['n']})" for e in hits[:3]) +
                     (f' +{len(hits) - 3}' if len(hits) > 3 else ''))
    impacts = [e for e in ev if 't' in e]
    if impacts:
        kinds = {}
        for e in impacts:
            kinds[e['kind']] = kinds.get(e['kind'], 0) + 1
        top = max(impacts, key=lambda e: e['db'])
        what = ', '.join(f"{c} {k}{'s' if c > 1 else ''}" for k, c in sorted(kinds.items(), key=lambda kv: -kv[1]))
        parts.append(f"{what} (loudest {clock(top['t'])})" if len(impacts) > 1 else f"{what} {clock(top['t'])}")
    tones = [e for e in ev if e['kind'] == 'tone']
    if tones:
        parts.append(', '.join(f"{e['desc']} {clock(e['t0'])}" for e in tones[:2]) +
                     (f' +{len(tones) - 2}' if len(tones) > 2 else ''))
    quiet = [e for e in ev if e['kind'] == 'quiet']
    if quiet:
        parts.append(f"quiet {span(quiet[0]['t0'], quiet[0]['t1'], 0)}" +
                     (f' +{len(quiet) - 1}' if len(quiet) > 1 else ''))
    if not parts:
        return 'nothing but talking/room tone'
    more = len(parts) - limit
    return '; '.join(parts[:limit]) + (f'; +{more} more' if more > 0 else '')


# ------------------------------------------------------------------ picture

AFPS = 10                                   # analysis frames per second
LONG = 320                                  # analysis size (long side, pixels)


def _video_stream(path):
    r = subprocess.run([str(FFPROBE), '-v', 'error', '-select_streams', 'v:0', '-show_streams', '-show_format',
                        '-of', 'json', str(path)], capture_output=True, text=True, errors='replace',
                       creationflags=NO_WINDOW)
    if r.returncode != 0:
        from letitedit.core import media
        raise media.unreadable(path, 'the picture', r.stderr)
    data = json.loads(r.stdout or '{}')
    st = (data.get('streams') or [None])[0]
    if not st:
        return None
    rot = 0
    for sd in st.get('side_data_list') or []:
        if 'rotation' in sd:
            rot = int(float(sd['rotation']))
    rot = rot or int(float((st.get('tags') or {}).get('rotate', 0) or 0))
    dur = float((data.get('format') or {}).get('duration') or st.get('duration') or 0)
    return {'w': int(st.get('width') or 0), 'h': int(st.get('height') or 0), 'rot': rot, 'duration': dur}


def _frames(path, info, start=0.0, dur=None, chunk=50):
    """Yield (k, H, W) uint8 gray chunks at AFPS in display orientation, for [start, start + dur) of the video.
    A reader thread keeps ffmpeg decoding while the caller computes."""
    import queue
    w, h = info['w'], info['h']
    if w >= h:
        W, H = LONG, max(2, int(round(LONG * h / w / 2)) * 2)
    else:
        H, W = LONG, max(2, int(round(LONG * w / h / 2)) * 2)
    # the display rotation is applied here: -noautorotate keeps ffmpeg's full-size transpose (slow) out of it.
    # No deblocking and no non-reference frames: about 30 % faster, and nothing this analysis can see.
    k = {90: 1, 270: -1, 180: 2}.get(info['rot'] % 360, 0)
    args = [str(FFMPEG), '-v', 'error', '-nostdin', '-skip_loop_filter', 'all', '-skip_frame', 'noref',
            '-noautorotate']
    if start:
        args += ['-ss', f'{start:.3f}']
    if dur:
        args += ['-t', f'{dur:.3f}']
    args += ['-i', str(path), '-an', '-sn', '-dn', '-vf', f'fps={AFPS},scale={W}:{H}:flags=fast_bilinear,format=gray',
             '-f', 'rawvideo', '-']
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    size = W * H
    q = queue.Queue(maxsize=6)

    def reader():
        try:
            while True:
                raw = proc.stdout.read(size * chunk)
                m = len(raw) // size
                if not m:
                    break
                q.put(raw[:m * size])
        except (OSError, ValueError):
            pass
        finally:
            q.put(None)
    th = threading.Thread(target=reader, daemon=True)
    th.start()
    try:
        while True:
            raw = q.get()
            if raw is None:
                break
            a = np.frombuffer(raw, np.uint8).reshape(-1, H, W)
            yield np.ascontiguousarray(np.rot90(a, k=k, axes=(1, 2))) if k else a
        # every frame read: a decoder that stopped on an error (a read that failed mid-file) is not a finished video
        if proc.wait() != 0:
            from letitedit.core import media
            raise media.unreadable(path, 'the picture' + (f' from {start:.0f} s' if start else ''))
    finally:
        if proc.poll() is None:
            proc.kill()
        while th.is_alive():            # let the reader finish (it may be blocked on a full queue)
            try:
                q.get(timeout=0.1)
            except Exception:  # noqa: BLE001
                pass
        proc.stdout.close()
        proc.wait()


def _phase(prev_f, cur_f, hh, ww):
    """Shifts (dx, dy) of cur relative to prev (content motion, pixels) and peak strength, from rfft2 spectra."""
    R = cur_f * np.conj(prev_f)
    R /= np.abs(R) + 1e-9
    c = np.fft.irfft2(R, s=(hh, ww), axes=(1, 2))
    n = c.shape[0]
    flat = c.reshape(n, -1)
    idx = flat.argmax(1)
    peak = flat[np.arange(n), idx]
    py, px = np.unravel_index(idx, (hh, ww))
    rows = np.arange(n)

    def sub(l, m, r):
        den = l - 2 * m + r
        return np.where(np.abs(den) > 1e-9, 0.5 * (l - r) / np.where(np.abs(den) > 1e-9, den, 1), 0).clip(-0.5, 0.5)
    dx = px + sub(c[rows, py, (px - 1) % ww], peak, c[rows, py, (px + 1) % ww])
    dy = py + sub(c[rows, (py - 1) % hh, px], peak, c[rows, (py + 1) % hh, px])
    dx = np.where(dx > ww / 2, dx - ww, dx)
    dy = np.where(dy > hh / 2, dy - hh, dy)
    return dx, dy, peak


SEGMENT_S = 45.0                  # long videos are measured in parallel pieces of about this length
G = 6                             # residual-motion grid (G x G cells) for 'where is the action'
SEG_WORKERS = max(2, min(8, (os.cpu_count() or 4) // 2))


def _segments(duration):
    if duration <= SEGMENT_S * 1.5:
        return [(0.0, None)]
    n = int(np.ceil(duration / SEGMENT_S))
    step = duration / n
    return [(round(i * step, 1), None if i == n - 1 else round(step, 1)) for i in range(n)]


def frame_metrics(path, info=None, start=0.0, dur=None):
    """Per analysis frame (AFPS) of [start, start + dur): content shift dx, dy (display widths per second; the first
    frame copies the second), phase-correlation peak, sharpness (Laplacian variance), mean luma, dark / clipped pixel
    shares, frame difference, G x G residual motion grid, 16-bin histogram, 8x8 thumbnail.
    Returns (dict of arrays, (H, W))."""
    info = info or _video_stream(path)
    if not info or not info['w']:
        return None, None
    cols = {k: [] for k in ('dx', 'dy', 'peak', 'sharp', 'luma', 'dark', 'clip', 'diff', 'grid', 'hist', 'sig')}
    prev_small = prev_f = None
    win = None
    shape = None
    for a in _frames(path, info, start, dur):
        x = a.astype(np.float32)
        m, H, W = x.shape
        shape = (H, W)
        lap = x[:, 1:-1, 1:-1] * 4
        lap -= x[:, :-2, 1:-1]
        lap -= x[:, 2:, 1:-1]
        lap -= x[:, 1:-1, :-2]
        lap -= x[:, 1:-1, 2:]
        flat = lap.reshape(m, -1)
        lm = flat.mean(1)
        cols['sharp'].append(np.einsum('ij,ij->i', flat, flat) / flat.shape[1] - lm * lm)
        cols['luma'].append(x.reshape(m, -1).mean(1))
        cols['dark'].append((a < 30).reshape(m, -1).mean(1))
        cols['clip'].append((a > 245).reshape(m, -1).mean(1))
        hh, ww = H // 2, W // 2
        small = x[:, 0:hh * 2:2, 0:ww * 2:2] + x[:, 1:hh * 2:2, 0:ww * 2:2]
        small += x[:, 0:hh * 2:2, 1:ww * 2:2]
        small += x[:, 1:hh * 2:2, 1:ww * 2:2]
        small *= 0.25
        if win is None:
            win = np.outer(np.hanning(hh), np.hanning(ww)).astype(np.float32)
        F = np.fft.rfft2((small - small.reshape(m, -1).mean(1)[:, None, None]) * win, axes=(1, 2))
        hist = np.bincount(((a[:, ::2, ::2] >> 4).reshape(m, -1).astype(np.int64) +
                            16 * np.arange(m)[:, None]).ravel(), minlength=16 * m).reshape(m, 16).astype(np.float32)
        cols['hist'].append(hist / hist.sum(1, keepdims=True))
        gh, gw = hh // 8, ww // 8
        cols['sig'].append(small[:, :gh * 8, :gw * 8].reshape(m, 8, gh, 8, gw).mean(axis=(2, 4)).reshape(m, 64))
        allf = F if prev_f is None else np.concatenate([prev_f[None], F])
        alls = small if prev_small is None else np.concatenate([prev_small[None], small])
        if len(allf) >= 2:
            dx, dy, pk = _phase(allf[:-1], allf[1:], hh, ww)
            diff = np.abs(alls[1:] - alls[:-1]).reshape(len(dx), -1).mean(1)
            # residual motion after removing the camera shift (whole pixels), on a 3x3 grid
            grids = np.zeros((len(dx), G * G), np.float32)
            for j in range(len(dx)):
                sx, sy = int(round(dx[j])), int(round(dy[j]))
                if abs(sx) >= ww // 3 or abs(sy) >= hh // 3:
                    continue
                y0, y1 = max(0, sy), hh + min(0, sy)
                x0, x1 = max(0, sx), ww + min(0, sx)
                r = np.abs(alls[j + 1][y0:y1, x0:x1] - alls[j][y0 - sy:y1 - sy, x0 - sx:x1 - sx])
                rh, rw = r.shape[0] // G, r.shape[1] // G
                if rh and rw:
                    grids[j] = r[:rh * G, :rw * G].reshape(G, rh, G, rw).mean(axis=(1, 3)).reshape(G * G)
            if prev_f is None:          # first frame: no motion measured before it; take the next one's
                dx, dy, pk, diff = (np.concatenate([v[:1], v]) for v in (dx, dy, pk, diff))
                grids = np.concatenate([grids[:1], grids])
            cols['dx'].append(dx / ww * AFPS)
            cols['dy'].append(dy / ww * AFPS)
            cols['peak'].append(pk)
            cols['diff'].append(diff)
            cols['grid'].append(grids)
        elif prev_f is None:
            for k, v in (('dx', [0.0]), ('dy', [0.0]), ('peak', [0.0]), ('diff', [0.0])):
                cols[k].append(np.array(v))
            cols['grid'].append(np.zeros((1, G * G), np.float32))
        prev_f, prev_small = F[-1], small[-1]
    if shape is None:
        return None, None
    out = {k: np.concatenate(v) if v else np.zeros(0) for k, v in cols.items()}
    n = len(out['luma'])
    for k in ('dx', 'dy', 'peak', 'diff'):
        out[k] = out[k][:n]
    out['grid'] = out['grid'][:n]
    return out, shape


def _merge_metrics(parts, starts):
    """Join per-segment metrics, each segment placed at its start time (AFPS frames)."""
    parts = [(p, s) for p, s in zip(parts, starts) if p[0] is not None]
    if not parts:
        return None, None
    out = {}
    for k in parts[0][0][0]:
        pieces, have = [], 0
        for (m, _), s in parts:
            first = int(round(s * AFPS))
            arr = m[k]
            if first > have and pieces:            # a gap (a piece came up short): repeat the last frame
                pieces.append(np.repeat(pieces[-1][-1:], first - have, axis=0))
                have = first
            elif first < have:                     # overlap: keep the earlier piece's frames
                arr = arr[have - first:]
            pieces.append(arr)
            have += len(arr)
        out[k] = np.concatenate(pieces)
    return out, parts[0][0][1]


PAN_WORDS = {('x', 1): 'pan left', ('x', -1): 'pan right', ('y', 1): 'tilt up', ('y', -1): 'tilt down'}


def _scene_changes(sig, secs, dark_mask, label, cuts):
    """Seconds where the camera shows something unlike the view before, without a cut (usable seconds only; at
    least 3 s apart)."""
    # big scene changes: the camera now shows something that does not resemble the view before
    sig_sec = np.array([sig[s * AFPS:(s + 1) * AFPS].mean(0) for s in range(secs)])
    contrast = sig_sec.std(1)
    z = sig_sec - sig_sec.mean(1, keepdims=True)
    z /= np.linalg.norm(z, axis=1, keepdims=True) + 1e-6
    changes = []
    ref = None
    for s in range(secs):
        usable = not dark_mask[s] and contrast[s] >= 4 and label[s] != 'fast whip'
        if not usable:
            continue
        if ref is None:
            ref = s
            continue
        cut_here = any(ref < c * 1.0 <= s + 0.999 for c in cuts)
        if cut_here:
            ref = s
            continue
        if float(z[s] @ z[ref]) < 0.25 and (s + 1 >= secs or float(z[s] @ z[s + 1]) > 0.5):
            if not changes or s - changes[-1] >= 3:
                changes.append(float(s))
            ref = s
    return changes


def _action_places(m, hd, diff, diff_med, spans, duration):
    """Adds to each steady span where the action is: residual motion on the G x G grid over its calm frames
    (or '')."""
    # where the action is in steady shots: residual motion energy on a G x G grid (skipping global changes)
    grid = m['grid']
    calm_frame = (hd < 0.25) & (diff < max(6.0, 3 * diff_med))
    for sp in spans:
        sp[1] = min(sp[1], duration) if duration else sp[1]
        if sp[2] not in ('steady', 'slight drift'):
            continue
        sel = slice(int(sp[0] * AFPS), int(sp[1] * AFPS))
        use = calm_frame[sel]
        if use.sum() < 5:
            sp.append('')
            continue
        g = grid[sel][use].sum(axis=0)
        if g.sum() / use.sum() / g.size < 1.2:     # nothing much moves
            sp.append('')
            continue
        g = g.reshape(G, G)
        pos = (np.arange(G) + 0.5) / G
        gx, gy = g.sum(0), g.sum(1)
        cx = float((gx * pos).sum() / gx.sum())
        cy = float((gy * pos).sum() / gy.sum())
        g3 = g.reshape(3, G // 3, 3, G // 3).sum(axis=(1, 3))
        conc = float(g3.max() / g3.sum())
        hx = 'left' if cx < 0.42 else 'right' if cx > 0.58 else 'centre'
        vy = 'top' if cy < 0.42 else 'bottom' if cy > 0.58 else 'middle'
        where = f'{vy}-{hx}' if (hx, vy) != ('centre', 'middle') else 'centre'
        sp.append(f'action {where} (x {cx:.2f}, y {cy:.2f}{", spread out" if conc < 0.2 else ""})')


def picture_analysis(m, shape, duration):
    """Spans and events from frame_metrics()."""
    n = len(m['luma'])
    res = {'v': VERSIONS['motion'], 'duration': round(float(duration), 2), 'size': list(shape)[::-1]}
    if n < 2:
        res.update(seconds=[], spans=[], dark=[], bright=[], blurry=[], cuts=[], changes=[])
        return res
    secs = int(np.ceil(n / AFPS))
    dx, dy, pk = m['dx'], m['dy'], m['peak']
    ok = pk >= 0.06
    sharp_sec, luma_sec, label, info = [], [], [], []
    diff_med = float(np.median(m['diff'][1:])) if n > 2 else 0.0
    for s in range(secs):
        j = slice(max(1, s * AFPS), min(n, (s + 1) * AFPS))
        if j.stop <= j.start:
            j = slice(max(0, n - 1), n)
        good = ok[j]
        vx, vy = dx[j][good], dy[j][good]
        speed = float(np.hypot(dx[j], dy[j]).mean()) if j.stop > j.start else 0.0
        if vx.size >= 2:
            mx, my = float(vx.mean()), float(vy.mean())
            jit = float(np.hypot(vx - mx, vy - my).mean())
        else:
            mx = my = 0.0
            jit = speed
        lost = 1 - float(good.mean()) if good.size else 1.0
        dd = float(m['diff'][j].mean())
        luma_sec.append(float(m['luma'][j].mean()))
        sharp_sec.append(float(np.median(m['sharp'][j])))
        mean_v = float(np.hypot(mx, my))
        if speed >= 1.2 or mean_v >= 0.9 or (lost >= 0.5 and dd >= max(12.0, 3 * diff_med)):
            lab = 'fast whip'
        elif jit >= 0.35:
            lab = 'shaky handheld'
        elif mean_v >= 0.08 and mean_v >= jit:
            axis, val = ('x', mx) if abs(mx) >= abs(my) else ('y', my)
            lab = ('slow ' if mean_v < 0.3 else '') + PAN_WORDS[(axis, 1 if val > 0 else -1)]
        elif jit >= 0.15 or speed >= 0.2:
            lab = 'handheld, some shake'
        elif speed >= 0.07 or jit >= 0.07:
            lab = 'slight drift'
        else:
            lab = 'steady'
        label.append(lab)
        info.append([round(speed, 3), round(jit, 3), round(mx, 3), round(my, 3), round(lost, 2), round(dd, 1)])
    # smooth: a single odd second between two equal labels takes theirs (not for whips)
    for s in range(1, secs - 1):
        if label[s - 1] == label[s + 1] != label[s] and 'fast whip' not in (label[s], label[s - 1]):
            label[s] = label[s - 1]
    spans = []
    for s, lab in enumerate(label):
        if spans and spans[-1][2] == lab:
            spans[-1][1] = s + 1
        else:
            spans.append([s, s + 1, lab])
    luma = np.array(luma_sec)
    dark_mask = luma < LIMITS['dark_luma']

    # cuts: one frame that differs hugely in structure from the one before, between two calmer moments
    cuts = []
    hist, sig, diff = m['hist'], m['sig'], m['diff']
    hd = np.concatenate([[0.0], np.abs(hist[1:] - hist[:-1]).sum(1)])
    zf = sig - sig.mean(1, keepdims=True)
    zn = np.linalg.norm(zf, axis=1)
    zf = zf / (zn[:, None] + 1e-6)
    same = np.concatenate([[1.0], (zf[1:] * zf[:-1]).sum(1)])       # structure kept from the frame before
    textured = sig.std(1) >= 3                                       # not black / flat frames
    textured = textured & np.concatenate([[False], textured[:-1]])
    for i in np.flatnonzero((hd >= 0.4) & (diff >= 15) & (same < 0.6) & textured):
        before, after = diff[max(1, i - 4):i], diff[i + 1:i + 5]
        if not (before.size and after.size):
            continue
        calm = max(float(np.median(before)), float(np.median(after)))
        steady_sides = float(np.median(pk[max(1, i - 4):i])) >= 0.2 and float(np.median(pk[i + 1:i + 5])) >= 0.2
        if diff[i] >= 4 * max(2.0, calm) and pk[i] < 0.2 and steady_sides:
            t = i / AFPS
            if not cuts or t - cuts[-1] > 1.0:
                cuts.append(round(t, 1))
    changes = _scene_changes(sig, secs, dark_mask, label, cuts)
    bounds = sorted(set([0] + [int(round(c)) for c in cuts] + [int(c) for c in changes] + [secs]))

    # blur: much softer than the seconds around it in the same scene (not when dark)
    sh = np.array(sharp_sec)
    near = np.zeros(secs)
    for a, b in zip(bounds, bounds[1:]):
        for s in range(a, b):
            near[s] = sh[max(a, s - 3):min(b, s + 4)].max()
    blur_mask = (sh < LIMITS['blur_near'] * near) & (sh < LIMITS['blur_median'] * float(np.median(sh))) & ~dark_mask
    blurry = []
    for a, b in _runs(blur_mask):
        moving = any(label[s] in ('fast whip', 'shaky handheld') for s in range(a, b))
        blurry.append([a, b, 'motion blur' if moving else 'out of focus?'])

    _action_places(m, hd, diff, diff_med, spans, duration)

    # exposure
    clip_sec = np.array([float(m['clip'][s * AFPS:(s + 1) * AFPS].mean()) for s in range(secs)])
    bright_mask = (clip_sec >= LIMITS['bright_clipped']) | (luma >= LIMITS['bright_luma'])
    dark = [[a, b, round(float(luma[a:b].mean()))] for a, b in _runs(dark_mask)]
    bright = [[a, b, round(float(clip_sec[a:b].mean()) * 100)] for a, b in _runs(bright_mask)]
    res.update(seconds=[[lab] + inf for lab, inf in zip(label, info)],
               spans=[[float(a), float(b), lab] + rest for a, b, lab, *rest in spans],
               dark=dark, bright=bright, blurry=blurry, cuts=cuts, changes=changes,
               sharp_median=round(float(np.median(sh)), 1), luma_median=round(float(np.median(luma)), 1),
               per_second={'luma': [round(float(x), 1) for x in luma], 'clipped': [round(float(x), 3) for x in clip_sec],
                           'sharp': [round(float(x), 2) for x in sh], 'near_sharp': [round(float(x), 2) for x in near],
                           'moving': [label[s] in ('fast whip', 'shaky handheld') for s in range(secs)]})
    return res


# What the picture labels mean (per second of video): dark = mean brightness (0-255) under dark_luma; blown out = at
# least bright_clipped of the pixels clipped, or mean brightness at least bright_luma; blurry = sharpness under
# blur_near x the sharpest second within 3 s in the same scene AND under blur_median x the clip's median (not when dark).
LIMITS = {'dark_luma': 40.0, 'bright_luma': 215.0, 'bright_clipped': 0.25, 'blur_near': 0.4, 'blur_median': 0.6}


def limits_text(limits=None):
    lim = {**LIMITS, **(limits or {})}
    return (f"picture labels: dark = brightness under {lim['dark_luma']:g}/255; blown out = {lim['bright_clipped']:.0%} "
            f"of pixels clipped or brightness {lim['bright_luma']:g}+; blurry = sharpness under {lim['blur_near']:g}x the "
            f"sharpest second nearby and {lim['blur_median']:g}x the clip's median (picture_limits sets them)")


def with_limits(res, limits=None):
    """The analysis with dark / bright / blurry spans recomputed for other cutoffs (keys of LIMITS); the same
    analysis when limits is empty or the analysis has no per-second values."""
    if not limits or not res or res.get('none') or not res.get('per_second'):
        return res
    lim = {**LIMITS, **{k: float(v) for k, v in limits.items() if k in LIMITS}}
    ps = res['per_second']
    luma, clip_ = np.array(ps['luma']), np.array(ps['clipped'])
    sh, near = np.array(ps['sharp']), np.array(ps['near_sharp'])
    dark_mask = luma < lim['dark_luma']
    bright_mask = (clip_ >= lim['bright_clipped']) | (luma >= lim['bright_luma'])
    blur_mask = (sh < lim['blur_near'] * near) & (sh < lim['blur_median'] * float(np.median(sh) if sh.size else 0)) & ~dark_mask
    out = dict(res)
    out['dark'] = [[a, b, round(float(luma[a:b].mean()))] for a, b in _runs(dark_mask)]
    out['bright'] = [[a, b, round(float(clip_[a:b].mean()) * 100)] for a, b in _runs(bright_mask)]
    out['blurry'] = [[a, b, 'motion blur' if any(ps['moving'][a:b]) else 'out of focus?'] for a, b in _runs(blur_mask)]
    out['limits'] = lim
    return out


def picture(path, refresh=False):
    """Camera motion, sharpness, exposure and scene changes of a video (cached by content). See picture_lines().
    Long videos are decoded in parallel pieces."""
    def compute():
        info = _video_stream(path)
        if not info or not info['w']:
            return {'v': VERSIONS['motion'], 'none': True}
        segs = _segments(info['duration'])
        if len(segs) == 1:
            m, shape = frame_metrics(path, info)
        else:
            ex = _seg_pool()
            parts = list(ex.map(lambda sd: frame_metrics(path, info, sd[0], sd[1]), segs))
            m, shape = _merge_metrics(parts, [s for s, _ in segs])
        if m is None:
            return {'v': VERSIONS['motion'], 'none': True}
        return picture_analysis(m, shape, info.get('duration') or len(m['luma']) / AFPS)
    return _cached('motion', path, compute, refresh)


def _clip_end(res, b):
    return min(float(b), res.get('duration') or float(b))


def coarse_spans(spans, limit):
    """At most `limit` spans for display: the shortest span merges into its longer neighbour until it fits."""
    spans = [list(sp) for sp in spans]
    while len(spans) > limit:
        i = min(range(len(spans)), key=lambda k: spans[k][1] - spans[k][0])
        if i == 0:
            j = 1
        elif i == len(spans) - 1:
            j = i - 1
        else:
            j = i - 1 if spans[i - 1][1] - spans[i - 1][0] >= spans[i + 1][1] - spans[i + 1][0] else i + 1
        a, b = min(spans[i][0], spans[j][0]), max(spans[i][1], spans[j][1])
        spans[j][0], spans[j][1] = a, b
        del spans[i]
        k = j if j < i else j - 1
        if k + 1 < len(spans) and spans[k + 1][2] == spans[k][2]:     # same label now adjacent: join
            spans[k][1] = spans[k + 1][1]
            del spans[k + 1]
        if k > 0 and spans[k - 1][2] == spans[k][2]:
            spans[k - 1][1] = spans[k][1]
            del spans[k]
    return spans


def picture_lines(res, limit=60):
    if res.get('none'):
        return ['no picture']
    out = [picture_summary(res)]
    spans = res['spans']
    if len(spans) > limit:
        spans = coarse_spans(spans, limit)
        out.append(f"(per-second detail merged to {len(spans)} spans; short moments go to their longer neighbour)")
    for sp in spans:
        a, b, lab = sp[0], _clip_end(res, sp[1]), sp[2]
        extra = f', {sp[3]}' if len(sp) > 3 and sp[3] else ''
        out.append(f'{span(a, b, 0)} {lab}{extra}')
    def more(items, n):
        return f' +{len(items) - n} more' if len(items) > n else ''
    extra = []
    if res['dark']:
        extra.append('dark ' + ', '.join(f'{span(a, _clip_end(res, b), 0)} (luma {l})' for a, b, l in res['dark'][:10])
                     + more(res['dark'], 10))
    if res['bright']:
        extra.append('blown out ' + ', '.join(f'{span(a, _clip_end(res, b), 0)} ({p}% clipped)'
                                            for a, b, p in res['bright'][:10]) + more(res['bright'], 10))
    if res['blurry']:
        extra.append('blurry ' + ', '.join(f'{span(a, _clip_end(res, b), 0)} ({w})' for a, b, w in res['blurry'][:12])
                     + more(res['blurry'], 12))
    if res['cuts']:
        extra.append('cuts at ' + ', '.join(clock(t) for t in res['cuts'][:30]) + more(res['cuts'], 30))
    if res['changes']:
        extra.append('big scene changes at ' + ', '.join(clock(t, 0) for t in res['changes'][:40]) +
                     more(res['changes'], 40))
    return out + extra


def picture_summary(res):
    """One short phrase for a folder listing: share of steady / moving / shaky time, the longest steady stretch,
    dark / blown-out spans, blurry seconds, cuts and scene changes."""
    if res.get('none'):
        return 'no picture'
    if not res['spans']:
        return 'too short to judge'
    total = sum(_clip_end(res, b) - a for a, b, *_ in res['spans']) or 1
    share = {}
    for a, b, lab, *_ in res['spans']:
        key = 'pan' if 'pan' in lab or 'tilt' in lab else lab
        share[key] = share.get(key, 0) + _clip_end(res, b) - a
    calm = (share.get('steady', 0) + share.get('slight drift', 0)) / total
    some = share.get('handheld, some shake', 0) / total
    rough = (share.get('shaky handheld', 0) + share.get('fast whip', 0)) / total
    pan = share.get('pan', 0) / total
    parts = [', '.join(x for x in (f'{calm:.0%} steady', f'{some:.0%} some shake' if some >= 0.05 else '',
                                   f'{pan:.0%} pans' if pan >= 0.05 else '',
                                   f'{rough:.0%} shaky/whips' if rough >= 0.05 else '') if x)]
    runs = []                       # stretches of steady / slight drift seconds
    for a, b, lab, *_ in res['spans']:
        if lab in ('steady', 'slight drift'):
            if runs and abs(runs[-1][1] - a) < 1e-6:
                runs[-1][1] = b
            else:
                runs.append([a, b])
    best = max(runs, key=lambda r: r[1] - r[0], default=None)
    if best and calm < 0.95 and _clip_end(res, best[1]) - best[0] >= 2:
        parts.append(f'longest steady {span(best[0], _clip_end(res, best[1]), 0)}')
    if res['dark']:
        parts.append('dark ' + ', '.join(span(a, _clip_end(res, b), 0) for a, b, _ in res['dark'][:2]) +
                     (f' +{len(res["dark"]) - 2}' if len(res['dark']) > 2 else ''))
    if res['bright']:
        parts.append('blown out ' + ', '.join(span(a, _clip_end(res, b), 0) for a, b, _ in res['bright'][:2]) +
                     (f' +{len(res["bright"]) - 2}' if len(res['bright']) > 2 else ''))
    if res['blurry']:
        secs = sum(_clip_end(res, b) - a for a, b, _ in res['blurry'])
        parts.append(f'blurry {secs:.0f} s')
    if res['cuts']:
        parts.append(f"{len(res['cuts'])} cut{'s' if len(res['cuts']) > 1 else ''}")
    if res['changes']:
        parts.append(f"{len(res['changes'])} scene change{'s' if len(res['changes']) > 1 else ''}")
    return '; '.join(parts)


# ------------------------------------------------------------------ music

MSR = 22050


def _beats_module():
    if str(CREATOR) not in sys.path:
        sys.path.insert(0, str(CREATOR))
    from letitedit_creator import beats
    return beats


def _segment(x, min_len, penalty):
    """Piecewise-constant fit of x (least squares + a penalty per segment); returns segment start indices."""
    n = len(x)
    if n < 2 * min_len:
        return [0]
    c1 = np.concatenate([[0.0], np.cumsum(x)])
    c2 = np.concatenate([[0.0], np.cumsum(x * x)])
    best = np.full(n + 1, np.inf)
    best[0] = 0.0
    prev = np.zeros(n + 1, int)
    for j in range(min_len, n + 1):
        i = np.arange(0, j - min_len + 1)
        i = i[np.isfinite(best[i])]
        if not i.size:
            continue
        ln = j - i
        cost = best[i] + (c2[j] - c2[i]) - (c1[j] - c1[i]) ** 2 / ln + penalty
        k = int(np.argmin(cost))
        best[j], prev[j] = cost[k], i[k]
    if not np.isfinite(best[n]):
        return [0]
    starts, j = [], n
    while j > 0:
        starts.append(int(prev[j]))
        j = prev[j]
    return sorted(starts)


def _sections(y, sr, downbeats, duration):
    hop = sr // 2
    n = len(y) // hop
    if n < 8:
        return []
    db = 10 * np.log10(np.mean(y[:n * hop].reshape(n, hop) ** 2, axis=1) + 1e-10)
    db = np.maximum(db, db.max() - 40)
    from scipy.ndimage import uniform_filter1d
    sm = uniform_filter1d(db, 6, mode='nearest')
    starts = _segment(sm, min_len=16, penalty=90.0)
    bounds = [s * 0.5 for s in starts] + [duration]
    # snap inner boundaries to a downbeat within 2 s
    for i in range(1, len(bounds) - 1):
        if downbeats:
            d = min(downbeats, key=lambda t: abs(t - bounds[i]))
            if abs(d - bounds[i]) <= 2:
                bounds[i] = d
    levels = []
    for a, b in zip(bounds, bounds[1:]):
        seg = db[int(a * 2):max(int(a * 2) + 1, int(b * 2))]
        levels.append(float(10 * np.log10(np.mean(10 ** (seg / 10)))))
    top = max(levels)
    out = []
    for i, ((a, b), lvl) in enumerate(zip(zip(bounds, bounds[1:]), levels)):
        rel = lvl - top
        seg = sm[int(a * 2):max(int(a * 2) + 2, int(b * 2))]
        slope = float(np.polyfit(np.arange(seg.size) * 0.5, seg, 1)[0]) if seg.size >= 4 else 0.0
        last = i == len(levels) - 1
        tail = db[max(0, int(b * 2) - 10):int(b * 2)]
        if i == 0 and rel <= -3 and len(levels) > 1:
            name = 'intro'
        elif last and len(levels) > 1 and (rel <= -3 or (tail.size >= 4 and tail[-1] < tail[0] - 8)):
            name = 'outro' + (' (fades out)' if tail.size >= 4 and tail[-1] < tail[0] - 8 else '')
        elif rel >= -1.5:
            name = 'peak'
        elif slope >= 0.12 and seg[-1] - seg[0] >= 3:
            name = 'build'
        elif rel <= -6:
            name = 'breakdown (quiet)'
        else:
            name = 'mid'
        out.append([round(a, 2), round(b, 2), name, round(rel, 1)])
    return out


def music(path, refresh=False):
    """Tempo, beats, downbeats and energy sections of a music file (cached by content), from the beat finder. Keys: duration, bpm, beats (count), pulse (0-1, how sure the beat
    finder is), beat_times, downbeats, sections [[start, end, name, dB vs loudest]]; beat_finder_error when it couldn't run (then no beats, and nothing guessed)."""
    import letitedit.sound.beat_finder as beat_finder
    reason = beat_finder.available()
    if reason:          # not kept: it may run next time
        return {'v': VERSIONS['beats'], 'bpm': None, 'beats': 0, 'pulse': 0.0, 'beat_times': [], 'downbeats': [], 'sections': [], 'beat_finder_error': reason}

    def compute():
        import letitedit.timing.music_sync as music_sync
        y = _decode_audio(path, MSR)
        dur = len(y) / MSR
        res = {'v': VERSIONS['beats'], 'duration': round(dur, 2)}
        empty = dict(bpm=None, beats=0, pulse=0.0, beat_times=[], downbeats=[])
        if dur < 4 or float(np.abs(y).max(initial=0)) < 1e-4:
            res.update(empty, sections=[])
            return res
        grid = music_sync.find_beats(path)
        if grid is None:
            res.update(empty, sections=_sections(y, MSR, [], dur))
            return res
        beats, pos, ex = grid
        times = [round(float(t), 3) for t in beats]
        down = [round(float(t), 3) for t, p in zip(beats, pos) if p == 0]
        res.update(bpm=round(float(ex['bpm']), 1), beats=len(times), pulse=round(float(np.mean(ex['beat_act'])), 3) if len(ex['beat_act']) else 0.0,
                   beat_times=times, downbeats=down, beats_per_bar=ex['bpb'])
        res['sections'] = _sections(y, MSR, down, dur)
        return res
    return _cached('beats', path, compute, refresh)


def music_brief(res):
    if not res.get('bpm'):
        return 'no steady beat'
    pulse = res.get('pulse', 0)
    word = 'strong' if pulse >= 0.6 else 'clear' if pulse >= 0.35 else 'weak'
    return f"{res['bpm']:g} bpm, {res['beats']} beats ({word} beat)"


def music_lines(res, max_beats=800):
    out = [music_brief(res)]
    if not res.get('bpm'):
        return out
    if res.get('sections'):
        out.append('sections (energy vs the loudest part): ' + ', '.join(
            f"{span(a, b, 0)} {name}{'' if rel == 0 else f' ({rel:+.0f} dB)'}" for a, b, name, rel in res['sections']))
    bt = res['beat_times']
    down = ', '.join(f'{t:.2f}' for t in res['downbeats'][:max_beats // 4])
    out.append(f'downbeats (bar starts, every 4 beats; s): {down}')
    out.append(f"beats (s){f' first {max_beats}' if len(bt) > max_beats else ''}: " +
               ', '.join(f'{t:.2f}' for t in bt[:max_beats]))
    return out


_RUNNING = {}                       # path -> future of a library_beats measurement still going
_RUNNING_LOCK = threading.RLock()     # re-entrant: a future done at once runs its callback right here
# The library's songs are measured by BEAT_WORKERS threads of their own, one song each at a time (the beat finder uses
# 4 threads per song). They are daemon threads, so the songs still waiting when the process ends are dropped, not
# measured first: a pool of the usual kind finishes everything queued before its process can exit, and a listing of
# 100 new songs then held a process open for minutes, its memory growing past 13 GB (T288). A song left unmeasured is
# measured the next time it is asked for; a result is written whole or not at all (_cached).
BEAT_WORKERS = 2
_BEAT_QUEUE = None
_BEAT_THREADS = []


def _beat_submit(path):
    """A future of music(path), measured on the library's own beat threads (started on first use)."""
    global _BEAT_QUEUE
    import queue
    from concurrent.futures import Future
    fut = Future()
    with _POOL_LOCK:
        if _BEAT_QUEUE is None:
            _BEAT_QUEUE = queue.Queue()
        _BEAT_THREADS[:] = [t for t in _BEAT_THREADS if t.is_alive()]
        while len(_BEAT_THREADS) < BEAT_WORKERS:
            t = threading.Thread(target=_beat_worker, args=(_BEAT_QUEUE,), daemon=True,
                                 name=f'library-beats-{len(_BEAT_THREADS) + 1}')
            t.start()
            _BEAT_THREADS.append(t)
        _BEAT_QUEUE.put((fut, path))
    return fut


def _beat_worker(jobs):
    while True:
        fut, path = jobs.get()
        if not fut.set_running_or_notify_cancel():
            continue
        try:
            fut.set_result(_safe(music, path))
        except BaseException as e:  # noqa: BLE001 - the waiting caller gets it; this thread goes on with the next song
            fut.set_exception(e)


def library_beats(paths, budget_s=10.0, compute=True, workers=None):
    """{path: music() result or None} for library files: cached ones at once; the others measured on the library's own
    beat threads within budget_s (None = not finished yet; it keeps going in the background and lands in the cache,
    unless the process ends first). A file whose measurement an earlier call left running is waited on, not measured
    twice. workers: not used (BEAT_WORKERS), kept for callers that pass it."""
    out, todo = {}, []
    for p in paths:
        try:
            if is_cached('beats', p):
                out[p] = music(p)
                continue
        except OSError:
            out[p] = None
            continue
        out[p] = None
        todo.append(p)
    if compute and todo:
        futs = {}
        with _RUNNING_LOCK:
            for p in todo:
                fut = _RUNNING.get(p)
                if fut is None:
                    fut = _RUNNING[p] = _beat_submit(p)
                    fut.add_done_callback(lambda done_fut, p=p: _forget_running(p, done_fut))
                futs[fut] = p
        done, _ = wait(futs, timeout=budget_s)
        for f in done:
            out[futs[f]] = f.result()
    return out


def _forget_running(path, fut):
    with _RUNNING_LOCK:
        if _RUNNING.get(path) is fut:
            del _RUNNING[path]


# ------------------------------------------------------------------ photos and text

def photo(path):
    """{'width', 'height' (as displayed), 'orientation', 'taken', 'camera', 'decoder'} of a still image."""
    from PIL import Image
    info = {'bytes': os.path.getsize(path)}
    try:
        if Path(path).suffix.lower() in ('.heic', '.heif', '.avif'):
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                info['preview'] = False
        with Image.open(path) as im:
            w, h = im.size
            exif = im.getexif()
            orient = exif.get(274, 1)
            if orient in (5, 6, 7, 8):
                w, h = h, w
            ex = exif.get_ifd(0x8769) if hasattr(exif, 'get_ifd') else {}
            taken = ex.get(36867) or ex.get(36868) or exif.get(306)
            model = ' '.join(str(x).strip() for x in (exif.get(271), exif.get(272)) if x)
            info.update(width=w, height=h, format=im.format)
            if taken:
                info['taken'] = str(taken).replace(':', '-', 2)[:16]
            if model:
                info['camera'] = model[:40]
    except Exception as e:  # noqa: BLE001
        info['error'] = f'{type(e).__name__}: {e}'[:120]
        info['preview'] = False
    if 'width' in info:
        w, h = info['width'], info['height']
        info['orientation'] = 'vertical' if h > w else 'horizontal' if w > h else 'square'
    if 'taken' not in info:
        info['modified'] = time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(path)))
    return info


def photo_image(path, width=360):
    """The photo as an upright RGB PIL image (thumbnail), or None."""
    from PIL import Image, ImageOps
    try:
        if Path(path).suffix.lower() in ('.heic', '.heif', '.avif'):
            import pillow_heif
            pillow_heif.register_heif_opener()
        with Image.open(path) as im:
            im.draft('RGB', (width * 2, width * 2))
            im = ImageOps.exif_transpose(im).convert('RGB')
            im.thumbnail((width, width * 2))
            return im
    except Exception:  # noqa: BLE001
        return None


def text(path, limit=4000):
    """(content, total characters) of a text file; content is the first `limit` characters."""
    with open(path, 'rb') as fh:
        raw = fh.read(max(limit * 4, 65536))
        rest = len(fh.read())
    for enc in ('utf-8-sig', 'utf-16') if not raw.startswith((b'\xff\xfe', b'\xfe\xff')) else ('utf-16',):
        try:
            s = raw.decode(enc)
            break
        except UnicodeDecodeError as e:
            if enc == 'utf-8-sig' and e.start > len(raw) - 4:
                s = raw[:e.start].decode(enc)
                break
    else:
        s = raw.decode('latin-1')
    total = len(s) + (rest if rest else 0)
    return s[:limit], total


# ------------------------------------------------------------------ many files at once

_POOL = None
_POOL_LOCK = threading.Lock()


def _pool(workers=None):
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = ThreadPoolExecutor(max_workers=workers or max(2, min(8, (os.cpu_count() or 4) // 2)),
                                       thread_name_prefix='perception')
        return _POOL


_SEG_POOL = None


def _seg_pool():
    """Decoding pieces of long videos: its own pool, so a worker of _pool() can wait on it without deadlock."""
    global _SEG_POOL
    with _POOL_LOCK:
        if _SEG_POOL is None:
            _SEG_POOL = ThreadPoolExecutor(max_workers=SEG_WORKERS, thread_name_prefix='perception-seg')
        return _SEG_POOL


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001
        return {'error': f'{type(e).__name__}: {e}'[:200]}


def analyze_many(videos, durations=None, workers=None):
    """{path: {'sounds': ..., 'picture': ...}} for many videos, computed in parallel (cached ones instantly).
    Longest files start first so the pool stays busy."""
    durations = durations or {}
    out = {str(p): {} for p in videos}
    ex = _pool(workers)
    jobs = []
    order = sorted(videos, key=lambda p: -float(durations.get(str(p), 0) or 0))
    for p in order:
        jobs.append((str(p), 'picture', ex.submit(_safe, picture, p)))
    for p in order:
        jobs.append((str(p), 'sounds', ex.submit(_safe, sounds, p)))
    for p, k, f in jobs:
        out[p][k] = f.result()
    return out


def uncached_seconds(videos, durations):
    """Seconds of video whose sound or picture analysis is not cached yet."""
    total = 0.0
    for p in videos:
        if not (is_cached('motion', p) and is_cached('sounds', p)):
            total += float(durations.get(str(p), 0) or 0)
    return total
