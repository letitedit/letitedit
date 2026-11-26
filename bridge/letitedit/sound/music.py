"""Music that follows the story.

The score op turns the music clips of an edit script into a bed that behaves like an editor would mix it: every song
brought to the same loudness, tucked under speech, up where nobody talks (montage), quiet or swelling where the edit
asks, crossfaded where songs meet and faded at the ends. It writes ordinary gain keyframes and audio fades on the
music clips, so the result shows (and can be adjusted by hand) in Shotcut like any volume automation.

Speech comes from the words: a file whose transcript is cached (letitedit_words) talks where its words are (each word
from 0.1 s before its start to 0.15 s after its end), so a drill, a fan or road noise never counts as talk. A file
without a transcript falls back to a voice detector (Silero, part of faster-whisper; run once per file and cached),
and the result says which files did (`speech_from`, `warning`).

Levels are relative to the dialogue's own loudness (measured over the speech, with clip and track gain), so
the balance holds whatever the source level: by default music sits 18 dB under speech, 6 dB under in montage.

Before the music, the score evens out the speech: each clip where someone talks gets a clip gain that brings its
speech to the same loudness as the others (level_voice: false leaves clip gains alone; {op: level} does only this).

Duet: speech pauses shorter than merge_gap (4 s) keep the music down, so a bed never pumps between sentences. To let
the music answer a line, name the pauses that open: `answer` (gap ids from the result's `gaps`, times, the phrase the
pause follows, or 'auto'). Each answered pause rises from just after the last word to just before the next, with its
own ramps scaled to the pause (a rise of up to a third of it, a fall of up to a quarter), so it is back down before
the next word.

    {op: score}                                         defaults from the style pack's `music` section
    {op: score, zones: [{from: '3:10', to: '3:45', level: swell}], end: 8, tracks: ['Music 1']}
    {op: score, answer: ['g4', {after: 'and then it quit on me'}, 63.2]}
    {op: score, answer: {auto: {min_pause: 2, spacing: 20}}}
    levels: talk | montage | quiet | swell | end, or a number of dB relative to the dialogue
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import hashlib
import math
import json
import os
import threading
import time
import re
import subprocess
from pathlib import Path

import numpy as np

CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache')))
FFMPEG = Path(os.environ.get('LETITEDIT_APP', (_SAI_ROOT + '\\app'))) / 'ffmpeg.exe'
MUSIC_NAME = re.compile(r'music|song|score|bed', re.I)
NOT_SPEECH_NAME = re.compile(r'music|song|score|bed|sfx|effect|sound|foley|ambien', re.I)
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
# Files from these folders are sound effects or songs, never what the person says, whatever their track is called
# (the speech model hears "Thank you." in a boom; T39 put effects on a track named "Hits").
SOUND_LIBRARY_DIRS = ('/assets/sfx/', '/sound effects/', '/music-library/')


def is_sound_library_file(path):
    """True when a clip's file lives in the asset library's sound effects, the person's Sound Effects folder or the
    music library: a track's name alone doesn't say what is on it."""
    p = '/' + str(path or '').replace('\\', '/').lower().lstrip('/')
    return any(d in p for d in SOUND_LIBRARY_DIRS)


def _identity(path):
    st = os.stat(path)
    return hashlib.sha256(f'{Path(path).resolve()}|{st.st_size}|{st.st_mtime_ns}'.encode()).hexdigest()[:16]


def _cached(kind, key, compute):
    folder = CACHE / kind
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f'{key}.json'
    if f.exists():
        try:
            with open(f, encoding='utf-8-sig') as fh:
                return json.load(fh)
        except ValueError:
            pass
    value = compute()
    # a temp name of its own: two threads computing the same key at once must not share one temp file
    tmp = f.with_name(f'{f.stem}.{os.getpid()}-{threading.get_ident()}.tmp')
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(value, fh)
    for _ in range(20):
        try:
            os.replace(tmp, f)
            break
        except PermissionError:     # a reader has the file open on Windows; try again
            time.sleep(0.05)
    else:
        tmp.unlink(missing_ok=True)
    return value


# ------------------------------------------------------------------ measurements

def _k_weighting(fs):
    """ITU-R BS.1770 K-weighting as two biquads (high shelf, then high pass) for sample rate fs."""
    import math
    G, Q, fc = 3.99984385397, 0.7071752369554193, 1681.9744509555319
    A, w0 = 10 ** (G / 40), 2 * math.pi * fc / fs
    al, c = math.sin(w0) / (2 * Q), math.cos(w0)
    shelf_b = [A * ((A + 1) + (A - 1) * c + 2 * math.sqrt(A) * al), -2 * A * ((A - 1) + (A + 1) * c),
               A * ((A + 1) + (A - 1) * c - 2 * math.sqrt(A) * al)]
    shelf_a = [(A + 1) - (A - 1) * c + 2 * math.sqrt(A) * al, 2 * ((A - 1) - (A + 1) * c),
               (A + 1) - (A - 1) * c - 2 * math.sqrt(A) * al]
    Q, fc = 0.5003270373253953, 38.13547087613982
    w0 = 2 * math.pi * fc / fs
    al, c = math.sin(w0) / (2 * Q), math.cos(w0)
    hp_b, hp_a = [(1 + c) / 2, -(1 + c), (1 + c) / 2], [1 + al, -2 * c, 1 - al]
    return (np.array(shelf_b) / shelf_a[0], np.array(shelf_a) / shelf_a[0]), (np.array(hp_b) / hp_a[0], np.array(hp_a) / hp_a[0])


def voice_profile(path):
    """{'voice': [[start, end], ...] seconds where someone talks, 'power': K-weighted mean-square power of every
    100 ms (BS.1770, all channels summed)} for a whole file; one decode, cached. The voice detector (Silero, from
    faster-whisper) tells voices from drills and road noise."""
    def compute():
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        from scipy.signal import lfilter, resample_poly
        fs = 48000
        proc = subprocess.Popen([str(FFMPEG), '-v', 'error', '-i', str(path), '-vn', '-ac', '2', '-ar', str(fs), '-f', 'f32le',
                                 '-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        (b1, a1), (b2, a2) = _k_weighting(fs)
        zi = None
        hop = fs // 10
        power, mono16, carry = [], [], np.zeros((0, 2), dtype=np.float32)
        while True:
            raw = proc.stdout.read(fs * 2 * 4 * 30)          # 30 s at a time
            if not raw:
                break
            block = np.frombuffer(raw[:len(raw) - len(raw) % 8], dtype=np.float32).reshape(-1, 2)
            if zi is None:
                zi = [np.zeros((2, 2)), np.zeros((2, 2))]
            y, zi[0] = lfilter(b1, a1, block, axis=0, zi=zi[0])
            y, zi[1] = lfilter(b2, a2, y, axis=0, zi=zi[1])
            y = np.concatenate([carry, y.astype(np.float32)])
            n = len(y) // hop
            if n:
                power.extend((np.square(y[:n * hop]).reshape(n, hop, 2).mean(axis=1).sum(axis=1)).tolist())
            carry = y[n * hop:]
            mono16.append(resample_poly(block.mean(axis=1), 1, 3).astype(np.float32))
        proc.stdout.close()
        if proc.wait() != 0:
            # no sound track: nothing talks (cached as before); a read or decode that failed: not cached
            from letitedit.core import media
            if media.audio_streams(path) == 0:
                return {'voice': [], 'power': []}
            raise media.unreadable(path, 'the sound')
        audio = np.concatenate(mono16) if mono16 else np.zeros(0, dtype=np.float32)
        voice = []
        if audio.size:
            opts = VadOptions(threshold=0.5, min_speech_duration_ms=250, min_silence_duration_ms=500, speech_pad_ms=120)
            voice = [[round(s['start'] / 16000, 3), round(s['end'] / 16000, 3)] for s in get_speech_timestamps(audio, opts)]
        return {'voice': voice, 'power': [float(f'{p:.4g}') for p in power]}
    return _cached('voice', _identity(path), compute)


def voice_times(path):
    """[[start, end], ...] source seconds where someone is talking in a file."""
    return voice_profile(path)['voice']


def integrated(powers):
    """BS.1770 integrated loudness of 100 ms K-weighted powers (400 ms blocks, 75 % overlap, both gates)."""
    p = np.asarray(powers, dtype=float)
    if p.size < 4:
        return -70.0
    blocks = np.convolve(p, np.ones(4) / 4, mode='valid')
    lufs = -0.691 + 10 * np.log10(np.maximum(blocks, 1e-12))
    gated = blocks[lufs > -70]
    if gated.size == 0:
        return -70.0
    rel = -0.691 + 10 * np.log10(gated.mean()) - 10
    final = gated[(-0.691 + 10 * np.log10(gated)) > rel]
    return round(float(-0.691 + 10 * np.log10(final.mean())), 2) if final.size else -70.0


def loudness(path, start=0.0, end=None):
    """Integrated loudness (LUFS) of a stretch of a file; -70 for silence (cached)."""
    key = f'{_identity(path)}-{float(start):.2f}-{(f"{float(end):.2f}" if end else "end")}'

    def compute():
        args = [str(FFMPEG), '-v', 'info', '-nostats', '-ss', f'{float(start):.3f}']
        if end:
            args += ['-t', f'{max(0.1, float(end) - float(start)):.3f}']
        args += ['-i', str(path), '-vn', '-af', 'ebur128=framelog=quiet', '-f', 'null', '-']
        r = subprocess.run(args, capture_output=True, text=True, errors='replace', creationflags=NO_WINDOW)
        err = r.stderr
        if r.returncode != 0:
            from letitedit.core import media
            if media.audio_streams(path) == 0:
                return -70.0
            raise media.unreadable(path, 'the sound', err)
        m = re.findall(r'I:\s+(-?[\d.]+|-?inf|nan)\s+LUFS', err)
        try:
            v = float(m[-1]) if m else -70.0
        except ValueError:
            v = -70.0
        return v if v == v and v > -70 else -70.0
    return _cached('loudness', key, compute)


# ------------------------------------------------------------------ the timeline

# How far the music sits under the voice while people talk, as letitedit_check_audio states it (T349: one rule for
# the check, the timing map and the review): short-term loudness readings (3 s, every 0.1 s) of the music and of the
# voice, once the first 3 s window has filled; a reading is talk while the voice reads over TALK_ABOVE_LUFS; at least
# TALK_READINGS of them (2 s); the median of voice minus music, in LU.
TALK_ABOVE_LUFS = -35.0
TALK_READINGS = 20


def music_below_voice_lu(pairs):
    """[(music short-term LUFS, voice short-term LUFS)] readings, the first 3 s already left out -> LU or None."""
    talk = [(m, d) for m, d in pairs if d is not None and m is not None and d > TALK_ABOVE_LUFS]
    if len(talk) < TALK_READINGS:
        return None
    gaps = sorted(d - m for m, d in talk)
    return round(gaps[len(gaps) // 2], 1)


def music_tracks(script, names=None):
    if names:
        return [t for t in script['tracks'] if t['name'] in names]
    import letitedit.sound.guide_song as guide_song       # T72: a song added when posting is not in the mix, so nothing levels it
    return [t for t in script['tracks'] if t.get('kind') == 'audio' and MUSIC_NAME.search(t['name'])
            and not guide_song.is_guide_name(t['name'])]


def _muted(item):
    return any(e == 'mute' or (isinstance(e, dict) and 'mute' in e) for e in item.get('effects', []))


def _static_gain(effects_or_gain):
    """dB of a static gain (a track's gain, or the gain effects of a clip); keyframed gain counts as 0."""
    if isinstance(effects_or_gain, (int, float)):
        return float(effects_or_gain)
    total = 0.0
    for e in effects_or_gain or []:
        if isinstance(e, dict) and isinstance(e.get('gain'), (int, float)):
            total += float(e['gain'])
    return total


def _key_time(t):
    if isinstance(t, (int, float)):
        return float(t)
    import letitedit.timeline.edit_script as es
    return float(es.to_seconds(t))


def clip_gain_db(effects, rel_s=0.0):
    """dB a clip's gain effects give rel_s seconds into the clip (timeline seconds): the static gains plus any keyframed
    gain ({'gain': {'keys': [[t, dB], ...]}}: straight lines between keys, held before the first and after the last)."""
    total = _static_gain(effects)
    for e in effects or []:
        if not (isinstance(e, dict) and isinstance(e.get('gain'), dict)):
            continue
        try:
            keys = sorted((_key_time(t), float(v)) for t, v in e['gain'].get('keys') or [])
        except (TypeError, ValueError):
            continue
        if not keys:
            continue
        if rel_s <= keys[0][0]:
            total += keys[0][1]
        elif rel_s >= keys[-1][0]:
            total += keys[-1][1]
        else:
            for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
                if t0 <= rel_s <= t1:
                    total += v0 if t1 - t0 < 1e-9 else v0 + (v1 - v0) * (rel_s - t0) / (t1 - t0)
                    break
    return total


def _keyframed(effects):
    return any(isinstance(x, dict) and isinstance(x.get('gain'), dict) for x in effects or [])


WORD_PAD_IN = 0.1     # a word's talk starts this long before its recognised start (the dip is done by then)
WORD_PAD_OUT = 0.15   # and ends this long after its end (the word's tail and a breath)
WORD_JOIN = 0.25      # words closer than this are one stretch of talk
WORD_MAX_S = 1.5      # the recogniser stretches a word over the hesitation after it ('know.' 92.9-96.8 s): talk is
                      # taken to last at most this long per word


def clip_speech(clip, a, b, prof=None):
    """Where someone talks inside the source range a-b of a file: ([[start, end], ...] source seconds, how).
    how = 'words' (the cached transcript: each word padded by WORD_PAD_IN / WORD_PAD_OUT, so a machine or ambience
    with no words is never talk) or 'voice' (the voice detector, for a file nobody has transcribed yet)."""
    ws = None
    try:
        import letitedit.footage.speech as speech_words
        ws = speech_words.cached_words(clip, max(0.0, a - 2.0), b + 1.0)
    except Exception:  # noqa: BLE001 - no transcript store: the voice detector decides
        ws = None
    if ws is not None:
        spans = []
        for w in ws:
            s, e = float(w['s']), float(w['e'])
            e = min(e, s + WORD_MAX_S)
            lo, hi = max(s - WORD_PAD_IN, a), min(e + WORD_PAD_OUT, b)
            if hi > lo:
                spans.append([lo, hi])
        return merge(spans, gap=WORD_JOIN), 'words'
    prof = prof or voice_profile(clip)
    return [[max(vs, a), min(ve, b)] for vs, ve in prof['voice'] if min(ve, b) > max(vs, a)], 'voice'


def speech(script, exclude=(), info=None):
    """Where someone is audibly talking on the timeline, and how loud: ([[start, end], ...] seconds, dialogue LUFS).
    Uses every non-music, non-effects track whose sound is on, with clip and track gain applied; word times where the
    file is transcribed, the voice detector where not (clip_speech). info (a dict) collects {'words': {files},
    'voice': {files}} and the timeline's words ('timeline_words': [{'w', 't0', 't1'}])."""
    from letitedit.timeline.edit_sync import layout
    spans, powers = [], []
    for t in script['tracks']:
        if t['name'] in exclude or NOT_SPEECH_NAME.search(t['name']) or t.get('hide') in ('audio', 'both'):
            continue
        track_gain = _static_gain(t.get('gain', 0) if not isinstance(t.get('gain'), dict) else 0)
        for it, s, e in layout(t):
            if 'clip' not in it or _muted(it) or not os.path.exists(it['clip']) or is_sound_library_file(it['clip']):
                continue
            a, b, speed = float(it['in']), float(it['out']), float(it.get('speed', 1.0))
            if speed > 1.5:
                continue  # fast-forwarded footage: no intelligible speech
            prof = voice_profile(it['clip'])
            scale = 10 ** ((track_gain + _static_gain(it.get('effects'))) / 10)
            got, how = clip_speech(it['clip'], a, b, prof)
            if info is not None:
                info.setdefault(how, set()).add(it['clip'])
                if how == 'words':
                    info.setdefault('timeline_words', []).extend(_timeline_words(it, s, e, a, b, speed))
            keyed = _keyframed(it.get('effects'))
            for lo, hi in got:
                spans.append([s + (lo - a) / speed, s + (hi - a) / speed])
                if keyed:       # a gain that changes inside the clip (phrase levelling): each reading at its own gain
                    k0 = int(lo * 10)
                    powers.extend(p * 10 ** ((track_gain + clip_gain_db(it.get('effects'), ((k0 + j) / 10 - a) / speed)) / 10)
                                  for j, p in enumerate(prof['power'][k0:int(hi * 10)]))
                else:
                    powers.extend(p * scale for p in prof['power'][int(lo * 10):int(hi * 10)])
    if info is not None:
        info['timeline_words'] = sorted(info.get('timeline_words', []), key=lambda w: w['t0'])
    return merge(spans), integrated(powers)


def _timeline_words(it, s, e, a, b, speed):
    """The cached words heard in a clip, in timeline seconds."""
    try:
        import letitedit.footage.speech as speech_words
        ws = speech_words.cached_words(it['clip'], max(0.0, a - 2.0), b + 1.0) or []
    except Exception:  # noqa: BLE001
        return []
    out = []
    for w in ws:
        ws_, we = float(w['s']), float(w['e'])
        inside = max(0.0, min(we, b) - max(ws_, a))
        if inside < 0.5 * max(1e-3, we - ws_):
            continue
        we = min(we, ws_ + WORD_MAX_S)
        out.append({'w': str(w['w']).strip(), 't0': round(s + (max(ws_, a) - a) / speed, 3),
                    't1': round(min(e, s + (min(we, b) - a) / speed), 3)})
    return out


def speech_spans(script, exclude=()):
    """Where someone is audibly talking on the timeline: [[start, end], ...] seconds."""
    return speech(script, exclude)[0]


def merge(spans, gap=0.0, min_len=0.0):
    out = []
    for s, e in sorted(spans):
        if out and s - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [x for x in out if x[1] - x[0] >= min_len]


# ------------------------------------------------------------------ levels

def _clock(v):
    from letitedit.timeline.edit_script import to_seconds
    return to_seconds(v)


def level_segments(total, talk, cfg, zones=(), end=0.0):
    """Piecewise-constant level (dB relative to the bed) over [0, total]: [(start, end, dB, name)]."""
    levels = cfg['zones']

    def level(v):
        if isinstance(v, (int, float)):
            return float(v), f'{float(v):+g} dB'
        if v not in levels:
            raise ValueError(f'unknown music level {v!r}: use {", ".join(levels)} or a number of dB')
        return float(levels[v]), v
    marks = []   # (start, end, priority, (dB, name))
    for s, e in talk:
        marks.append((s, e, 1, level('talk')))
    if end:
        marks.append((max(0.0, total - float(end)), total, 2, level('end')))
    for z in zones:
        if isinstance(z, (list, tuple)):          # [from, to] or [from, to, level]
            z = {'from': z[0], 'to': z[1], **({'level': z[2]} if len(z) > 2 else {})}
        marks.append((_clock(z['from']), _clock(z['to']), 3, level(z.get('level', 'montage'))))
    edges = sorted({0.0, total, *[m[0] for m in marks], *[m[1] for m in marks]})
    edges = [x for x in edges if 0 <= x <= total]
    segs = []
    base = level('montage')
    for a, b in zip(edges, edges[1:]):
        if b - a < 1e-6:
            continue
        mid = (a + b) / 2
        hit = max((m for m in marks if m[0] <= mid < m[1]), key=lambda m: m[2], default=None)
        val = hit[3] if hit else base
        if segs and segs[-1][2] == val[0] and segs[-1][3] == val[1]:
            segs[-1] = (segs[-1][0], b, val[0], val[1])
        else:
            segs.append((a, b, val[0], val[1]))
    return segs


def curve(segs, attack, release, ramps=None):
    """Control points (t, dB) of the level with ramps: down-ramps finish as the quieter part starts (so the first
    word is already clear), up-ramps start as it ends. ramps: [(from, to, attack, release)] spans (answered pauses,
    zones with their own ramps) whose edges use their own fall (attack) and rise (release) seconds."""
    if not segs:
        return []

    def own(T):
        for z0, z1, att, rel in ramps or ():
            if abs(T - z0) < 1e-4 or abs(T - z1) < 1e-4:
                return att, rel
        return None

    pts = [(segs[0][0], segs[0][2])]
    for i in range(1, len(segs)):
        a, b = segs[i - 1][2], segs[i][2]
        T = segs[i][0]
        att, rel = own(T) or (attack, release)
        if b < a:
            t0 = max(T - att, pts[-1][0], segs[i - 1][0])
            pts += [(t0, a), (T, b)]
        else:
            t1 = min(T + rel, segs[i][1])
            pts += [(T, a), (t1, b)]
    pts.append((segs[-1][1], segs[-1][2]))
    out = []
    for t, v in pts:
        if out and abs(out[-1][0] - t) < 1e-6:
            out[-1] = (t, v)
        else:
            out.append((t, v))
    return out


def value_at(pts, t):
    if t <= pts[0][0]:
        return pts[0][1]
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if t0 <= t <= t1:
            return v0 if t1 - t0 < 1e-9 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return pts[-1][1]


def _simplify(keys):
    out = []
    for k in keys:
        if len(out) >= 2:
            (t0, v0), (t1, v1) = out[-2], out[-1]
            if abs(v0 - v1) < 0.05 and abs(v1 - k[1]) < 0.05:
                out[-1] = k
                continue
        out.append(k)
    return out


# ------------------------------------------------------------------ the duet: pauses the music answers

MIN_ANSWER_S = 0.75     # shortest pause the music can rise in (between the padded words: a 1 s pause between words)
ANSWER_LEVEL = 'swell'
AUTO_ANSWER = {'min_pause': 2.0, 'spacing': 20.0, 'sentence': True, 'level': ANSWER_LEVEL, 'max_per_minute': 3.0}
_GAP_ID = re.compile(r'^g\d+$')


def speech_gaps(spans, words=()):
    """The pauses between stretches of talk, in time order: [{'id': 'g1', 'from', 'to', 'len', 'pause', 'after',
    'before'}]. from-to is where the music may be up (after the last word's tail, before the next word's dip, the
    pads of clip_speech); pause is the silence between the words themselves; after/before: the words around it."""
    out, n = [], 0
    for (s0, e0), (s1, e1) in zip(spans, spans[1:]):
        if s1 - e0 < 0.3:
            continue
        n += 1
        prev = [w for w in words if w['t1'] <= e0 + 1e-3 and w['t1'] >= e0 - 4.0]
        nxt = [w for w in words if w['t0'] >= s1 - 1e-3 and w['t0'] <= s1 + 4.0]
        pause = (nxt[0]['t0'] - prev[-1]['t1']) if prev and nxt else (s1 - e0)
        out.append({'id': f'g{n}', 'from': round(e0, 3), 'to': round(s1, 3), 'len': round(s1 - e0, 3),
                    'pause': round(pause, 3), 'after': ' '.join(w['w'] for w in prev[-6:]),
                    'before': ' '.join(w['w'] for w in nxt[:4])})
    return out


def _gap_text(g):
    return (f"{g['id']} {_fmt(g['from'])}-{_fmt(g['to'])} ({g['len']:.2f} s up, pause {g['pause']:.2f} s)"
            + (f" after \"{g['after']}\"" if g.get('after') else ''))


def _tokens(text):
    return [t for t in re.findall(r"[a-z0-9']+", str(text).lower().replace('’', "'")) if t]


def _resolve_gap(item, gaps, words):
    """The pause an `answer` entry names: a gap id ('g4'), a time (s or 'm:ss'), a phrase ('...the line') or
    {gap | at | after (+ near)}. Raises ValueError naming the pauses nearby."""
    from letitedit.timeline.edit_script import to_seconds
    opts = item if isinstance(item, dict) else {}
    if isinstance(item, str) and _GAP_ID.match(item.strip()):
        opts = {'gap': item.strip()}
    elif isinstance(item, str) and re.fullmatch(r'\d+(\.\d+)?|\d+:\d+(\.\d+)?', item.strip()):
        opts = {'at': item}
    elif isinstance(item, str):
        opts = {'after': item}
    elif isinstance(item, (int, float)) and not isinstance(item, bool):
        opts = {'at': item}

    def near_text(t):
        close = sorted(gaps, key=lambda g: abs((g['from'] + g['to']) / 2 - t))[:3]
        return '; '.join(_gap_text(g) for g in close) or 'no pauses on the timeline'
    if opts.get('gap'):
        g = next((g for g in gaps if g['id'] == opts['gap']), None)
        if g is None:
            raise ValueError(f"answer: no pause {opts['gap']} (pauses g1-g{len(gaps)}; the score's result lists them)")
        return g, opts
    if opts.get('at') is not None:
        t = to_seconds(opts['at'])
        inside = [g for g in gaps if g['from'] - 0.3 <= t <= g['to'] + 0.3]
        if inside:
            return min(inside, key=lambda g: abs((g['from'] + g['to']) / 2 - t)), opts
        raise ValueError(f'answer: {_fmt(t)} is not in a pause between words; nearest: {near_text(t)}')
    if opts.get('after'):
        want = _tokens(opts['after'])
        if not want:
            raise ValueError(f"answer: after {opts['after']!r} has no words")
        if not words:
            raise ValueError('answer: after needs the words (transcripts); give gap ids or times instead')
        toks = [(_tokens(w['w']) or [''])[0] for w in words]
        hits = [k for k in range(len(toks) - len(want) + 1) if toks[k:k + len(want)] == want]
        if not hits:
            raise ValueError(f"answer: \"{opts['after']}\" is not said on the timeline (as transcribed); "
                             'letitedit_words(project=...) shows the words')
        if opts.get('near') is not None:
            nt = to_seconds(opts['near'])
            hits.sort(key=lambda k: abs(words[k]['t0'] - nt))
        last = words[hits[0] + len(want) - 1]
        g = next((g for g in gaps if last['t1'] - 0.05 <= g['from'] <= last['t1'] + 0.6), None)
        if g is None:
            nxt = next((w for w in words if w['t0'] >= last['t1'] - 1e-3 and w is not last), None)
            raise ValueError(f"answer: no pause after \"{opts['after']}\" ({_fmt(last['t1'])}): "
                             + (f"\"{nxt['w']}\" follows {nxt['t0'] - last['t1']:.2f} s later; " if nxt else '')
                             + 'widen the pause with picture first, or answer a pause nearby: ' + near_text(last['t1']))
        if len(hits) > 1 and opts.get('near') is None:
            opts = {**opts, '_also': [round(words[k]['t0'], 1) for k in hits[1:4]]}
        return g, opts
    raise ValueError(f'answer entries are a pause id (g4), a time, a phrase, or {{gap | at | after, level?, attack?, '
                     f'release?}}; got {item!r}')


def _inside_talk(g, talk):
    return any(s <= g['from'] + 1e-3 and g['to'] <= e + 1e-3 for s, e in talk)


def answers(spec, gaps, words, talk, attack, release, merge_gap):
    """The pauses `answer` opens: ([{gap, from, to, len, level, attack, release, after}], notes)."""
    if not spec:
        return [], []
    items = spec if isinstance(spec, list) else [spec]
    chosen, notes = {}, []
    for item in items:
        if item == 'auto' or (isinstance(item, dict) and 'auto' in item):
            rule = dict(AUTO_ANSWER)
            if isinstance(item, dict):
                rule.update(item['auto'] if isinstance(item['auto'], dict) else {})
                rule.update({k: v for k, v in item.items() if k in ('level', 'attack', 'release')})
            punct = any(str(w['w'])[-1:] in '.?!' for w in words)
            last_end, per_min = -1e9, {}
            for g in gaps:
                if g['pause'] < float(rule['min_pause']) or g['len'] < MIN_ANSWER_S or not _inside_talk(g, talk):
                    continue
                if rule.get('sentence', True) and punct and str(g['after'])[-1:] not in '.?!':
                    continue
                if g['from'] - last_end < float(rule['spacing']):
                    continue
                minute = int(g['from'] // 60)
                if per_min.get(minute, 0) >= float(rule.get('max_per_minute') or 99):
                    continue
                chosen.setdefault(g['id'], (g, {k: rule[k] for k in ('level', 'attack', 'release') if k in rule}))
                per_min[minute] = per_min.get(minute, 0) + 1
                last_end = g['to']
            if not any(o for o in chosen.values()):
                notes.append(f"answer auto: no pause of {float(rule['min_pause']):g} s or more"
                             + (' after a sentence' if rule.get('sentence', True) and punct else '')
                             + f" inside the talk (pauses of {merge_gap:g} s or more are up already)")
            continue
        g, opts = _resolve_gap(item, gaps, words)
        chosen[g['id']] = (g, opts)
        if opts.get('_also'):
            notes.append(f"answer after \"{opts.get('after')}\": said again at "
                         f"{', '.join(_fmt(t) for t in opts['_also'])}; the first was used (near: s picks another)")
    out = []
    for gid, (g, opts) in sorted(chosen.items(), key=lambda kv: kv[1][0]['from']):
        L = float(g['len'])
        if L < MIN_ANSWER_S:
            raise ValueError(f"answer {gid}: the pause {_gap_text(g)} leaves {L:.2f} s between the words' tails, too "
                             f"short for the music to rise and fall back before the next word (needs {MIN_ANSWER_S:g} s, "
                             f"a pause of about {MIN_ANSWER_S + WORD_PAD_IN + WORD_PAD_OUT:.2f} s): widen it with "
                             'picture first')
        rel = float(opts['release']) if opts.get('release') is not None else min(release, max(0.12, L / 3))
        att = float(opts['attack']) if opts.get('attack') is not None else min(attack, max(0.1, L / 4))
        if rel + att > 0.9 * L:
            k = 0.9 * L / (rel + att)
            rel, att = rel * k, att * k
        lvl = opts.get('level', ANSWER_LEVEL)
        out.append({'gap': gid, 'from': g['from'], 'to': g['to'], 'len': L, 'level': lvl, 'attack': round(att, 3),
                    'release': round(rel, 3), 'after': g.get('after')})
        if not _inside_talk(g, talk):
            notes.append(f"answer {gid}: the pause is {g['pause']:.1f} s, longer than merge_gap ({merge_gap:g} s), so "
                         f"the music is up there anyway; the answer sets its level to {lvl}")
    for x, y in zip(out, out[1:]):
        if y['from'] - x['to'] < 8.0:
            notes.append(f"answered pauses {x['gap']} and {y['gap']} are {y['from'] - x['to']:.1f} s apart: quick "
                         'rises and dips sound like pumping; 3-4 answers per scene, in the pauses after key lines')
    return out, notes


# ------------------------------------------------------------------ the op

VOICE_MIN_S = 0.8      # a clip needs this much detected speech to be levelled
VOICE_MAX_DB = 12.0    # largest correction either way
VOICE_STEP_DB = 1.0    # smaller differences are left alone
PHRASE_MIN_S = 0.6     # a phrase this long, inside a clip, is levelled on its own when it would sit
PHRASE_STEP_DB = 6.0   # this far off the target after the clip's gain (two voices at different levels in one clip,
                       # a line said much more softly); smaller differences are the delivery and stay
PHRASE_GAP_S = 0.1     # words further apart than this (on their sound), or a full stop, start a new phrase
PHRASE_RAMP_S = 0.12   # the gain moves at most this fast, centred in the gap between the two phrases


def _phrases(clip, a, b, prof):
    """The phrases said in a clip's source range a-b: [(start, end)] source seconds, split at a full stop or a gap of
    PHRASE_GAP_S between words, measured on their sound (speech.sound_words); the stretches of talk (clip_speech) for
    a file with no cached words."""
    try:
        import letitedit.footage.speech as speech_words
        ws = [w for w in speech_words.sound_words(clip, a, b, cached=True) or []
              if min(float(w['e']), b) - max(float(w['s']), a) > 0.5 * (float(w['e']) - float(w['s']))]
    except Exception:  # noqa: BLE001 - no words: the stretches of talk
        ws = []
    if not ws:
        return [(lo, hi) for lo, hi in clip_speech(clip, a, b, prof)[0]]
    out = [[max(a, float(ws[0]['s'])), min(b, float(ws[0]['e']))]]
    for prev, w in zip(ws, ws[1:]):
        ws_, we_ = max(a, float(w['s'])), min(b, float(w['e']))
        if ws_ - out[-1][1] >= PHRASE_GAP_S or str(prev['w']).rstrip().endswith(('.', '?', '!')):
            out.append([ws_, we_])
        else:
            out[-1][1] = max(out[-1][1], we_)
    return [(lo, hi) for lo, hi in out if hi > lo]


def _phrase_keys(spans, gains, a, b, speed):
    """Gain keys (clip-relative timeline seconds) that hold each stretch of talk at its own gain and move between
    them inside the pause that separates them."""
    rel = lambda t: round((t - a) / speed, 3)
    keys = [[0.0, gains[0]]]
    for (lo0, hi0), (lo1, hi1), g0, g1 in zip(spans, spans[1:], gains, gains[1:]):
        if g0 == g1:
            continue
        mid, ramp = (hi0 + lo1) / 2, min(PHRASE_RAMP_S, max(0.03, lo1 - hi0))
        keys += [[rel(max(a, mid - ramp / 2)), g0], [rel(min(b, mid + ramp / 2)), g1]]
    keys.append([rel(b), gains[-1]])
    out = []
    for k in keys:          # no repeated times, and nothing that only repeats the gain before and after it
        if out and abs(k[0] - out[-1][0]) < 1e-3:
            out[-1] = k
        else:
            out.append(k)
    return out


def _speech_lufs(prof, phrases, talk, talk_powers, scale):
    """A clip's speech loudness for levelling, and the loud stretches to level on their own: (lufs, [(lo, hi, lufs)]).
    Measured on its stretches of talk (`talk` and their powers, clip_speech), as always, unless those measure
    PHRASE_STEP_DB or more louder than its phrases (word times measured on their sound, _phrases): then a loud sound
    the phrases don't hold (a shout, a laugh, a bump inside a padded word) would set the gain of all the talk around
    it. The phrases are measured instead, and each stretch of talk outside them that sits PHRASE_STEP_DB or more over
    them is returned to get its own gain (however short). Phrases holding under PHRASE_MIN_S of sound, or measuring as
    silence, leave the talk."""
    power = prof['power']
    span = lambda lo, hi: range(int(lo * 10), min(len(power), int(math.ceil(hi * 10))))
    loud_of = integrated([p * scale for p in talk_powers])
    if sum(hi - lo for lo, hi in phrases) < PHRASE_MIN_S:
        return loud_of, []
    inside = {i for lo, hi in phrases for i in span(lo, hi)}
    words = integrated([power[i] * scale for i in sorted(inside)])
    if words <= -70 or loud_of - words < PHRASE_STEP_DB:
        return loud_of, []
    outside = sorted({i for lo, hi in talk for i in span(lo, hi)} - inside)
    groups = []
    for i in outside:
        if groups and i == groups[-1][-1] + 1:
            groups[-1].append(i)
        else:
            groups.append([i])
    db = lambda frames: -0.691 + 10 * math.log10(max(sum(power[i] for i in frames) * scale / len(frames), 1e-12))
    loud = []
    for g in groups:                # each stretch from its first to its last loud reading, so the move sits in the gap
        hot = [i for i in g if db([i]) - words >= PHRASE_STEP_DB]
        if hot:
            frames = list(range(hot[0], hot[-1] + 1))
            if db(frames) - words >= PHRASE_STEP_DB:
                loud.append((frames[0] / 10, (frames[-1] + 1) / 10, db(frames)))
    return words, loud


def level_voice(script, op=None, exclude=()):
    """Even out the speech: every clip with at least VOICE_MIN_S of speech (its words, or the voice detector when it
    has no transcript; not muted, not fast-forwarded, no keyframed gain) gets a clip gain that brings its speech
    loudness to `target` (default: the median of the clips). Inside a clip, a phrase (_phrases) of PHRASE_MIN_S or more
    that would still sit PHRASE_STEP_DB or more off the target (two voices at different levels, a line said much more
    softly) gets its own level, the gain moving in the gap before it (keyframed gain). A clip whose talk measures
    PHRASE_STEP_DB or more louder than its phrases (a loud sound outside the words) is measured on its phrases and the
    loud stretch gets its own level, however short (_speech_lufs). Edits the script in place;
    returns a summary."""
    from letitedit.timeline.edit_sync import layout
    op = op or {}
    rows = []
    for t in script['tracks']:
        if t['name'] in exclude or NOT_SPEECH_NAME.search(t['name']) or t.get('hide') in ('audio', 'both'):
            continue
        track_gain = _static_gain(t.get('gain', 0) if not isinstance(t.get('gain'), dict) else 0)
        for it, s, e in layout(t):
            if 'clip' not in it or _muted(it) or not os.path.exists(it['clip']) or float(it.get('speed', 1.0)) > 1.5                     or is_sound_library_file(it['clip']):
                continue
            if _keyframed(it.get('effects')):
                continue
            a, b = float(it['in']), float(it['out'])
            prof = voice_profile(it['clip'])
            powers, secs = [], 0.0
            talk = clip_speech(it['clip'], a, b, prof)[0]
            for lo, hi in talk:
                secs += hi - lo
                powers.extend(prof['power'][int(lo * 10):int(hi * 10)])
            if secs < VOICE_MIN_S:
                continue
            g = _static_gain(it.get('effects'))
            scale = 10 ** ((g + track_gain) / 10)
            spans = _phrases(it['clip'], a, b, prof)
            lufs, loud = _speech_lufs(prof, spans, talk, powers, scale)
            if lufs > -70:
                phrases = [(lo, hi, integrated([p * scale for p in prof['power'][int(lo * 10):int(math.ceil(hi * 10))]])
                            if hi - lo >= PHRASE_MIN_S else None) for lo, hi in spans]
                phrases = sorted(phrases + loud)
                rows.append((it, s, g, lufs, phrases, a, b, float(it.get('speed', 1.0))))
    if not rows:
        return {'levelled': 0, 'note': 'no clips with enough speech to level'}
    vals = sorted(r[3] for r in rows)
    target = float(op['target']) if op.get('target') is not None else vals[len(vals) // 2]
    changed, phrased = [], []
    clamp = lambda d: max(-VOICE_MAX_DB, min(VOICE_MAX_DB, d))
    for it, s, g, lufs, phrases, a, b, speed in rows:
        delta = clamp(target - lufs)
        new = round((g + delta) * 2) / 2
        gains = []
        for lo, hi, pl in phrases:
            own = round((g + clamp(target - pl)) * 2) / 2 if pl is not None and pl > -70 else new
            gains.append(own if abs(own - new) >= PHRASE_STEP_DB else new)
        effects = list(it.get('effects') or [])
        idx = next((i for i, x in enumerate(effects) if isinstance(x, dict) and isinstance(x.get('gain'), (int, float))), None)
        if len(set(gains)) > 1:
            keys = _phrase_keys([(lo, hi) for lo, hi, _ in phrases], gains, a, b, speed)
            effects = [x for x in effects if not (isinstance(x, dict) and isinstance(x.get('gain'), (int, float)))]
            effects.insert(idx if idx is not None else len(effects), {'gain': {'keys': keys}})
            it['effects'] = effects
            moved = [(round(lo, 2), gg) for (lo, hi, _), gg in zip(phrases, gains) if gg != new]
            phrased.append(f"{it.get('id')}: {new - g:+g} dB, and "
                           + ', '.join(f"{gg - g:+g} dB from source {lo:.2f} s" for lo, gg in moved[:4])
                           + f" (speech was {round(lufs, 1)} LUFS; those stretches sat {PHRASE_STEP_DB:g}+ dB off the rest)")
            continue
        if abs(delta) < VOICE_STEP_DB:
            continue
        effects = [x for x in effects if not (isinstance(x, dict) and isinstance(x.get('gain'), (int, float)))]
        effects.insert(idx if idx is not None else len(effects), {'gain': new})
        it['effects'] = effects
        changed.append((it.get('id'), round(lufs, 1), round(new - g, 1)))
    spread = (round(vals[0], 1), round(vals[-1], 1))
    out = {'levelled': len(changed) + len(phrased), 'speech_clips': len(rows), 'target_lufs': round(target, 1),
           'speech_range_before': f'{spread[0]} to {spread[1]} LUFS',
           'changes': ([f'{iid}: {d:+g} dB (speech was {l} LUFS)' for iid, l, d in changed] + phrased)[:40]}
    if phrased:
        out['phrases_levelled'] = len(phrased)
    return out


def score(script, op, kit=None):
    """Apply {op: score, ...} to a script in place; returns a summary for the change notes."""
    from letitedit.timeline.edit_sync import layout
    import letitedit.timeline.edit_script as es
    kit = kit or es.kit_for(script)
    cfg = {**kit['music'], 'zones': {**kit['music']['zones'], **(op.get('levels') or {})}}
    for k in ('attack', 'release', 'crossfade', 'fade_in', 'fade_out', 'merge_gap', 'dialogue_lufs'):
        if op.get(k) is not None:
            cfg[k] = float(op[k])
    tracks = music_tracks(script, op.get('tracks'))
    if not tracks:
        raise ValueError('No music track found (name one with tracks: [...] or call it "Music ...").')
    reset, kept = [], []
    for t in tracks:
        # the score sets the music level: the editor's automatic ducking would stack on top of it, and so would an old
        # project's very low track volume (-32 dB); a small track volume is kept as a deliberate offset
        g = t.get('gain')
        if isinstance(g, dict) or (g not in (None, 0, 0.0) and abs(float(g)) > 12) or t.get('duck'):
            reset.append(f"{t['name']} (track volume {g if not isinstance(g, dict) else 'keyframed'}"
                         f"{', auto-duck' if t.get('duck') else ''})")
            t['gain'] = 0.0
            t.pop('duck', None)
        elif g not in (None, 0, 0.0):
            kept.append(f"{t['name']} {float(g):+g} dB")
    voice = None
    if op.get('level_voice', True):
        voice = level_voice(script, {'target': op.get('voice_lufs')}, exclude={t['name'] for t in tracks})
    total = es.to_seconds(script.get('length', 0))
    placed = [(t, it, s, e) for t in tracks for it, s, e in layout(t) if 'clip' in it and not _muted(it)]
    if not placed:
        raise ValueError('The music tracks have no clips to score.')
    total = max(total, max(e for *_, e in placed))
    info = {}
    spans, dialogue = speech(script, exclude={t['name'] for t in tracks}, info=info)
    if cfg.get('dialogue_lufs') is not None:
        dialogue = float(cfg['dialogue_lufs'])
    elif dialogue <= -70:
        dialogue = float(kit['export'].get('loudness', -14.0))   # nobody talks: treat the music as the programme
    merge_gap = float(cfg.get('merge_gap', 4.0))
    talk = merge(spans, gap=merge_gap, min_len=0.35) if cfg.get('duck_under_speech', True) else []
    attack, release = float(cfg.get('attack', 0.25)), float(cfg.get('release', 0.8))
    gaps = speech_gaps(spans, info.get('timeline_words') or [])
    answered, answer_notes = answers(op.get('answer'), gaps, info.get('timeline_words') or [], talk, attack,
                                     release, merge_gap)
    zones = [dict(z) if isinstance(z, dict) else z for z in (op.get('zones') or [])]
    ramps = []
    for z in zones:
        if isinstance(z, dict) and (z.get('attack') is not None or z.get('release') is not None):
            ramps.append((_clock(z['from']), _clock(z['to']), float(z.get('attack', attack)),
                          float(z.get('release', release))))
    for a_ in answered:
        zones.append({'from': a_['from'], 'to': a_['to'], 'level': a_['level']})
        ramps.append((a_['from'], a_['to'], a_['attack'], a_['release']))
    segs = level_segments(total, talk, cfg, zones, float(op.get('end', 0) or 0))
    pts = curve(segs, attack, release, ramps)
    summary = []
    for t, it, s, e in placed:
        a, b = float(it['in']), float(it['out'])
        lufs = loudness(it['clip'], a, b)
        # zone levels are relative to the dialogue: bring each song to the dialogue's loudness first
        base = max(-40.0, min(15.0, dialogue - lufs)) if lufs > -70 else 0.0
        keys = [[0.0, round(base + value_at(pts, s), 2)]]
        keys += [[round(tt - s, 3), round(base + v, 2)] for tt, v in pts if s < tt < e]
        keys.append([round(e - s, 3), round(base + value_at(pts, e), 2)])
        keys = _simplify(keys)
        fade_in, fade_out = _fades(placed, it, s, e, total, cfg)
        # fades the clip already has are kept (score adds its own only where there is none)
        had = {k for x in it.get('effects', []) if isinstance(x, dict) for k in x if k in ('fade_in_audio', 'fade_out_audio')}
        effects = [x for x in it.get('effects', []) if not (isinstance(x, dict) and 'gain' in x)]
        new = [{'gain': {'keys': keys}}]
        if fade_in and 'fade_in_audio' not in had:
            new.append({'fade_in_audio': round(fade_in, 2)})
        if fade_out and 'fade_out_audio' not in had:
            new.append({'fade_out_audio': round(fade_out, 2)})
        it['effects'] = new + effects
        ducks = sum(1 for x in segs if x[3] == 'talk' and x[1] > s and x[0] < e)
        summary.append(f"{os.path.basename(it['clip'])}: {lufs:.1f} LUFS, {base:+.1f} dB to match the dialogue, "
                       f"{ducks} dip(s) under speech, fades {fade_in:g}/{fade_out:g} s")
    talk_s = sum(min(e2, total) - s2 for s2, e2 in talk)
    z = cfg['zones']
    op['_result'] = {'dialogue_lufs': round(dialogue, 1),
                     'music_levels': {k: round(dialogue + float(v), 1) for k, v in z.items()},
                     'songs': summary, 'speech_seconds': round(talk_s, 1), 'total_seconds': round(total, 1),
                     'zones': [f'{_fmt(a)}-{_fmt(b)} {name}' for a, b, _, name in segs if name != 'talk'][:20]}
    if voice is not None:
        op['_result']['speech_levelled'] = voice
    if reset:
        op['_result']['reset'] = 'set to 0 dB, auto-duck off: ' + '; '.join(reset)
    if kept:
        op['_result']['track_volume_kept'] = 'on top of the score: ' + '; '.join(kept)
    by_words, by_voice = sorted(info.get('words', ())), sorted(info.get('voice', ()))
    op['_result']['speech_from'] = {'words': len(by_words), 'voice_detector': len(by_voice)}
    warnings = []
    if by_voice:
        names = ', '.join(os.path.basename(f) for f in by_voice[:8]) + (' ...' if len(by_voice) > 8 else '')
        warnings.append(f'{len(by_voice)} file(s) have no transcript, so speech there was found by the voice detector '
                        f'(machines and ambience can count as talk): {names}. letitedit_words(clip) transcribes one; '
                        'score again to duck by word times.')
    listed = [g for g in gaps if g['len'] >= MIN_ANSWER_S]
    op['_result']['gaps'] = [_gap_text(g) for g in listed[:40]] + (
        [f'... {len(listed) - 40} more (answer by id, time or phrase)'] if len(listed) > 40 else [])
    if answered:
        op['_result']['answered'] = [
            f"{a_['gap']} {_fmt(a_['from'])}-{_fmt(a_['to'])} ({a_['len']:.2f} s) at {a_['level']}, rise "
            f"{a_['release']:.2f} s, fall {a_['attack']:.2f} s" + (f" after \"{a_['after']}\"" if a_.get('after') else '')
            for a_ in answered]
    warnings += answer_notes
    norm = [m for m in script.get('master') or [] if 'loudness' in m]
    if warnings:
        op['_result']['warning'] = ' | '.join(warnings)
    if norm:
        op['_result']['warning'] = (op['_result']['warning'] + ' | ' if op['_result'].get('warning') else '') + (
            f"the master has a dynamic loudness normaliser (window {float((norm[0]['loudness'] or {}).get('window', 10)):g} s, "
            f"up to +{float((norm[0]['loudness'] or {}).get('max_gain', 15)):g} dB): it lifts quiet stretches and works against the music zones. "
            "Prefer {op: master, effects: [{limiter: {limit_db: -1.5}}]} and set the final loudness at export.")
    return op['_result']


def _fades(placed, it, s, e, total, cfg):
    xf = float(cfg.get('crossfade', 3.0))
    fade_in = fade_out = None
    for _, other, os_, oe in placed:
        if other is it:
            continue
        if os_ < s < oe:                      # another song still playing when this one starts: crossfade
            fade_in = max(fade_in or 0, min(xf, oe - s))
        elif abs(oe - s) < 0.1:               # butted: short dip
            fade_in = max(fade_in or 0, xf / 2)
        if os_ < e < oe:
            fade_out = max(fade_out or 0, min(xf, e - os_))
        elif abs(os_ - e) < 0.1:
            fade_out = max(fade_out or 0, xf / 2)
    if fade_in is None:
        fade_in = float(cfg.get('fade_in', 1.5))
    if fade_out is None:
        fade_out = float(cfg.get('fade_out', 3.0))
    length = e - s
    return min(fade_in, length / 2), min(fade_out, length / 2)


def _fmt(t):
    return f'{int(t // 60)}:{t % 60:04.1f}'
