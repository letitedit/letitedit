"""The measurements of each take (sound, picture, speech).

Part of `takes` (letitedit/footage/takes.py), which imports every name here back,
so `takes.X` is the same object it always was.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
import json
import math
import subprocess
import threading
import numpy as np
import letitedit.timeline.cutpoints as cutpoints  # noqa: E402
import letitedit.footage.speech as speech  # noqa: E402
from letitedit.footage.takes_words import (  # noqa: E402
    APP, DOUBLES, FFMPEG, NO_WINDOW, _ISNUM, _content, _is_filler
)
from letitedit.footage.takes_sources import (  # noqa: E402
    _tok_text
)


# ------------------------------------------------------------------ measurements

def _overlap(a, b, spans):
    return sum(max(0.0, min(b, y) - max(a, x)) for x, y in spans)


_CHANNELS = {}


def _sound_format(path):
    """(channels, sample rate) of the first sound stream; (0, 0) without sound. Decoding at these keeps every
    channel's own level (an up- or down-mix changes peaks and can hide clipping; resampling rings at clipped tops)."""
    if path not in _CHANNELS:
        ch, sr = 0, 0
        try:
            r = subprocess.run([str(APP / 'ffprobe.exe'), '-v', 'error', '-select_streams', 'a:0', '-show_entries',
                                'stream=channels,sample_rate', '-of', 'json', str(path)], capture_output=True,
                               text=True, creationflags=NO_WINDOW, timeout=60)
            s = (json.loads(r.stdout or '{}').get('streams') or [{}])[0]
            ch, sr = int(s.get('channels') or 0), int(s.get('sample_rate') or 0)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        _CHANNELS[path] = (ch, sr)
    return _CHANNELS[path]


def _decode(path, a, b):
    """(float samples [n, channels], sample rate) of path from a to b seconds, at the file's own channels and rate;
    (None, 0) without sound."""
    ch, sr = _sound_format(path)
    if ch <= 0 or sr <= 0:
        return None, 0
    try:
        r = subprocess.run([str(FFMPEG), '-v', 'error', '-nostdin', '-ss', f'{max(0.0, a):.3f}', '-t',
                            f'{max(0.05, b - a):.3f}', '-i', str(path), '-vn', '-sn', '-dn', '-ac', str(ch), '-ar',
                            str(sr), '-f', 'f32le', '-'], capture_output=True, creationflags=NO_WINDOW, timeout=180)
    except (OSError, subprocess.SubprocessError):
        return None, 0
    data = r.stdout[:len(r.stdout) // (4 * ch) * (4 * ch)]
    if not data:
        return None, 0
    return np.frombuffer(data, np.float32).reshape(-1, ch), sr


CLIP_LEVEL = 0.99          # |sample| at or above this (about -0.09 dBFS) counts as clipped
CLIP_RUN = 3               # ...when at least this many samples in a row are (flat-topped)
HOP_S = 0.01


def _audio_measures(path, take, doc, st, ctx_words):
    """Audio of a take with context: peak, clipping, speech level, noise floor (in the pauses), and the envelope
    for the sheet. Returns (measures, envelope dict)."""
    dur = doc.duration or (take['end'] + 5)
    a = max(0.0, take['start'] - st['context_s'] - 0.5)
    b = min(dur, take['end'] + st['context_s'] + 0.5)
    x, rate = _decode(path, a, b)
    if x is None or len(x) < rate * 0.05:
        return {'available': False, 'why': 'no sound decoded'}, None
    n = int(rate * HOP_S)
    mono = x.mean(axis=1)
    frames = mono[:len(mono) // n * n].reshape(-1, n)
    env = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-7)
    tc = a + (np.arange(len(env)) + 0.5) * HOP_S
    s0, s1 = int((take['start'] - a) * rate), int((take['end'] - a) * rate)
    seg = x[max(0, s0):max(s0 + 1, s1)]
    peak = float(np.abs(seg).max()) if seg.size else 0.0
    hot = np.abs(seg) >= CLIP_LEVEL
    clipped = int(hot.sum())
    run_ms, runs = 0.0, 0
    for ch in range(hot.shape[1] if hot.ndim == 2 else 0):
        m = np.concatenate([[False], hot[:, ch], [False]])
        d = np.flatnonzero(np.diff(m.astype(np.int8)))
        lens = d[1::2] - d[::2]
        long_ = lens[lens >= CLIP_RUN]
        runs = max(runs, int(long_.size))
        run_ms = max(run_ms, float(long_.sum()) / rate * 1000)
    in_words = np.zeros(len(env), bool)
    near_words = np.zeros(len(env), bool)
    for w in ctx_words:
        ws_, we_ = float(w['s']), float(w['e'])
        near_words |= (tc >= ws_ - 0.08) & (tc <= we_ + 0.08)
        if take['start'] - 1e-6 <= ws_ and we_ <= take['end'] + 1e-6:
            in_words |= (tc >= ws_) & (tc <= we_)
    speech_db = float(np.median(env[in_words])) if in_words.sum() >= 5 else None
    quiet = env[~near_words]
    noise_db = float(np.percentile(quiet, 15)) if quiet.size >= 30 else None
    out = {'available': True, 'peak_dbfs': round(20 * math.log10(peak + 1e-9), 1), 'clipped_samples': clipped,
           'clip_runs': runs, 'clipped_ms': round(run_ms, 1),
           'speech_db': None if speech_db is None else round(speech_db, 1),
           'noise_db': None if noise_db is None else round(noise_db, 1),
           'snr_db': None if speech_db is None or noise_db is None else round(speech_db - noise_db, 1),
           'measured_window': [round(a, 2), round(b, 2)]}
    if noise_db is None:
        out['noise_note'] = 'not enough pause around the take to measure the noise floor'
    head = env[:5] if a <= 0.001 else None
    tail = env[-5:] if dur and b >= dur - 0.02 else None
    return out, {'a': a, 'env': env, 'head': head, 'tail': tail}


def _edges(take, doc, envd, speech_db, st, path_ok):
    ws = doc.ws
    k0, k1 = take['k0'], take['k1']
    prev_e = float(ws[k0 - 1]['e']) if k0 > 0 else None
    next_s = float(ws[k1 + 1]['s']) if k1 + 1 < len(ws) else None
    dur = doc.duration
    lead = take['start'] - (prev_e if prev_e is not None else 0.0)
    tail = ((next_s if next_s is not None else dur) - take['end']) if (next_s is not None or dur) else None
    out = {'lead_in_s': round(lead, 2), 'tail_out_s': None if tail is None else round(tail, 2),
           'before': 'word' if prev_e is not None else 'recording start',
           'after': 'word' if next_s is not None else ('recording end' if dur else 'unknown'),
           'first_word_p': ws[k0].get('p'), 'last_word_p': ws[k1].get('p')}
    first_cut = last_cut = None
    if prev_e is None:
        if take['start'] >= 0.25:
            first_cut = False
        elif envd is not None and envd.get('head') is not None and speech_db is not None:
            first_cut = bool(float(np.mean(envd['head'])) >= speech_db - 10)
    else:
        first_cut = False
    if next_s is None and dur:
        if dur - take['end'] >= 0.25:
            last_cut = False
        elif envd is not None and envd.get('tail') is not None and speech_db is not None:
            last_cut = bool(float(np.mean(envd['tail'])) >= speech_db - 10)
    elif next_s is not None:
        last_cut = False
    out['first_word_cut_by_recording_start'] = first_cut
    out['last_word_cut_by_recording_end'] = last_cut
    if path_ok:
        try:
            cin, cout = cutpoints.snap(doc.file, take['start'], take['end'], prev_e, next_s)
            out['cut_in'], out['cut_out'] = cin, cout
        except Exception:  # noqa: BLE001
            pass
    out['tight_in'] = bool(lead < 0.1)
    out['tight_out'] = bool(tail is not None and tail < 0.1)
    return out


def _restarts(T):
    """Repeats inside a take ('now now', 'it's kind of it's kind of'): [(lo, hi, kind)] token ranges."""
    found, used, n = [], set(), len(T)
    for size in (5, 4, 3, 2, 1):
        for i in range(0, n - size):
            for k in range(i + size, min(n - size, i + size + 3) + 1):
                if T[i:i + size] != T[k:k + size]:
                    continue
                if size == 1 and (k != i + 1 or T[i] in DOUBLES or _ISNUM.match(T[i])):
                    continue
                if size >= 2 and k != i + size and not any(_content(t) for t in T[i:i + size]):
                    continue
                if any(j in used for j in range(i, k + size)):
                    continue
                found.append((i, k + size, 'repeat' if k == i + size else 'restart'))
                used.update(range(i, k + size))
                break
    return sorted(found)


def _delivery(take, node_unit, lo, hi, doc, st):
    ws = doc.ws
    k0, k1 = take['k0'], take['k1']
    pauses = []
    for k in range(k0 + 1, k1 + 1):
        gap = float(ws[k]['s']) - float(ws[k - 1]['e'])
        if gap >= st['long_pause_s']:
            pauses.append([round(float(ws[k - 1]['e']), 2), round(gap, 2)])
    fillers = [str(ws[k]['w']).strip() for k in range(k0, k1 + 1) if _is_filler(ws[k]['w'])]
    T = node_unit.toks[take['tlo']:take['thi']]
    rs = []
    take['_restart_k'] = set()
    for a, b, kind in _restarts(T):
        ta, tb = take['tlo'] + a, take['tlo'] + b
        rs.append({'kind': kind, 'text': _tok_text(node_unit, ta, tb),
                   'at': round(float(ws[node_unit.tw0[ta]]['s']), 2)})
        take['_restart_k'].update(range(node_unit.tw0[ta], node_unit.tw1[tb - 1] + 1))
    dur = max(0.01, take['end'] - take['start'])
    nwords = sum(1 for k in range(k0, k1 + 1) if not _is_filler(ws[k]['w']))
    return {'duration_s': round(dur, 2), 'words': nwords, 'words_per_s': round(nwords / dur, 2),
            'pauses': {'count': len(pauses), 'longest_s': max((p[1] for p in pauses), default=0.0),
                       'total_s': round(sum(p[1] for p in pauses), 2), 'at': pauses[:10]},
            'restarts': rs[:10], 'restart_count': len(rs),
            'fillers': {'count': len(fillers), 'words': fillers[:12]}}


def _transcript_conf(take, doc):
    ps = [float(doc.ws[k]['p']) for k in range(take['k0'], take['k1'] + 1) if doc.ws[k].get('p') is not None]
    if not ps:
        return {'available': False, 'why': 'the transcript has no word probabilities'}
    unsure = [str(doc.ws[k]['w']).strip() for k in range(take['k0'], take['k1'] + 1)
              if doc.ws[k].get('p') is not None and float(doc.ws[k]['p']) < speech.UNSURE]
    return {'available': True, 'mean_p': round(float(np.mean(ps)), 3), 'min_p': round(float(min(ps)), 3),
            'unsure_words': unsure[:12], 'unsure_count': len(unsure)}


def _noise(take, sounds):
    if sounds is None:
        return {'available': False, 'why': 'no cached sound analysis (analyze=True makes one)'}
    if sounds.get('silent'):
        return {'available': True, 'silent': True, 'impacts': [], 'sustained': []}
    a, b = take['start'], take['end']
    impacts, sustained = [], []
    for e in sounds.get('events') or []:
        if 't' in e:
            if a <= e['t'] <= b:
                impacts.append({'t': e['t'], 'kind': e['kind'], 'over_room_db': e.get('over')})
        elif e.get('kind') in ('sustained', 'hits', 'tone'):
            ov = _overlap(a, b, [(e['t0'], e['t1'])])
            if ov > 0:
                desc = e.get('desc') or e['kind']
                if e['kind'] == 'hits':
                    desc = f"repeated hits x{e.get('n', '?')} (hammering?)"
                else:
                    try:
                        import letitedit.footage.perception as pc
                        desc = pc._short(desc)
                    except Exception:  # noqa: BLE001
                        pass
                sustained.append({'t0': e['t0'], 't1': e['t1'], 'kind': e['kind'], 'desc': desc,
                                  'share_of_take': round(ov / max(0.01, b - a), 2),
                                  'loud': e.get('loud') or '', 'over_room_db': e.get('over')})
    return {'available': True, 'impacts': impacts[:8], 'impact_count': len(impacts), 'sustained': sustained[:6],
            'loud_background': bool(sounds.get('loud_background')), 'room_db': sounds.get('room_db'),
            'file_speech_db': sounds.get('speech_db')}


def _picture(take, pic):
    if pic is None:
        return {'available': False, 'why': 'no cached picture analysis (analyze=True makes one)'}
    if pic.get('none'):
        return {'available': False, 'why': 'no picture (sound file)'}
    a, b = take['start'], take['end']
    d = max(0.01, b - a)
    share = lambda spans: round(_overlap(a, b, [(s[0], s[1]) for s in spans]) / d, 2)
    shaky = [(sp[0], sp[1]) for sp in pic.get('spans') or [] if sp[2] in ('shaky handheld', 'fast whip')]
    labels = {}
    for sp in pic.get('spans') or []:
        ov = _overlap(a, b, [(sp[0], sp[1])])
        if ov > 0:
            labels[sp[2]] = labels.get(sp[2], 0) + ov
    out = {'available': True, 'dark': share(pic.get('dark') or []), 'blown_out': share(pic.get('bright') or []),
           'blurry': share(pic.get('blurry') or []), 'shaky': share([(x, y) for x, y in shaky]),
           'camera': max(labels, key=labels.get) if labels else None,
           'cuts_inside': [c for c in pic.get('cuts') or [] if a < c < b]}
    ps = pic.get('per_second') or {}
    sh = ps.get('sharp') or []
    if sh:
        secs = [s for s in range(int(a), int(math.ceil(b))) if 0 <= s < len(sh)]
        med = pic.get('sharp_median') or float(np.median(sh))
        if secs and med:
            out['sharpness_vs_clip'] = round(float(np.median([sh[s] for s in secs])) / float(med), 2)
    return out


def _voice(take, doc, voice):
    if voice is None:
        return None
    a, b = take['start'], take['end']
    words = [(float(doc.ws[k]['s']), float(doc.ws[k]['e'])) for k in range(take['k0'], take['k1'] + 1)]
    voiced = [(max(a, x), min(b, y)) for x, y in voice if y > a and x < b]
    v_total = sum(y - x for x, y in voiced)
    covered = 0.0
    for x, y in voiced:
        covered += _overlap(x, y, [(s - 0.1, e + 0.1) for s, e in words])
    w_total = sum(e - s for s, e in words)
    w_voiced = sum(_overlap(s, e, voice) for s, e in words)
    return {'voice_without_words_s': round(max(0.0, v_total - covered), 2),
            'words_without_voice_s': round(max(0.0, w_total - w_voiced), 2)}


class _FileCache:
    """Per-file analyses read once (from caches; computed only with analyze=True)."""

    def __init__(self, analyze):
        self.analyze = analyze
        self.lock = threading.Lock()
        self.data = {}

    def get(self, kind, path):
        key = (kind, path)
        with self.lock:
            if key in self.data:
                return self.data[key]
        val = None
        try:
            if kind in ('sounds', 'motion'):
                import letitedit.footage.perception as pc
                if self.analyze or pc.is_cached(kind, path):
                    val = pc.sounds(path) if kind == 'sounds' else pc.picture(path)
            elif kind == 'voice':
                import letitedit.sound.music as music
                if self.analyze or (music.CACHE / 'voice' / f'{music._identity(path)}.json').exists():
                    val = music.voice_times(path)
        except Exception:  # noqa: BLE001 - an analysis that fails is unknown, not a pass
            val = None
        with self.lock:
            self.data[key] = val
        return val
