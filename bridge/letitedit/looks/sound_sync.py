"""Sounds tied to the picture: a click on each transition and a key tick on each caption word.

analyse()  measures them in a reference's non-voice sound: how many cuts carry a click, how long after the cut it
           starts, how loud it is against the voice, its shape; and whether short quiet clicks follow word or
           caption arrivals more often than chance.
plan()     places them in a project: a click on each cutaway transition (or every cut) and a tick on each caption
           word, at the learned level and offset, thinned so no two sounds are closer than the sound itself.
           Returns {op: fx} items ({kind: sfx, ...}) for letitedit_timeline_apply.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

FORMAT = 'letitedit-synced-sounds/1'
ROLES = {'transition_click': 'transition', 'word_click': 'caption_word'}
# the library sounds each role draws on (asset ids in assets/manifest)
DEFAULT_SOUNDS = {'transition_click': ['library/camera-shutter_click_04', 'library/camera-shutter_click_02'],
                  'word_click': ['synth/key-click-1', 'synth/key-click-2', 'synth/key-click-3']}


# ------------------------------------------------------------------ measuring a reference

def detect_impulses(y, sr, hp=5000.0, ratio_db=14.0, ctx_s=0.012, min_gap_s=0.02):
    """Clicks: spikes of high-frequency energy, about a millisecond wide, standing ratio_db over the local median."""
    from scipy import signal
    from scipy.ndimage import median_filter
    y = np.asarray(y, dtype=np.float64)
    if y.ndim > 1:
        y = y.mean(axis=1)
    hp = min(hp, sr / 2 * 0.8)
    sos = signal.butter(4, hp, 'hp', fs=sr, output='sos')
    a = np.abs(signal.sosfilt(sos, y))
    w = max(1, int(0.0005 * sr))
    e = np.convolve(a, np.ones(w) / w, 'same')
    stride = 8
    size = int(2 * ctx_s * sr / stride) + 1
    wide = np.repeat(median_filter(e[::stride], size=size, mode='nearest'), stride)[:len(e)]
    r = 20 * np.log10((e + 1e-9) / (wide + 1e-9))
    peaks, _ = signal.find_peaks(r, height=ratio_db, distance=max(1, int(min_gap_s * sr)))
    out = []
    for p in peaks:
        lo = p
        while lo > 0 and e[lo] > e[p] * 0.5 and p - lo < 0.02 * sr:
            lo -= 1
        hi = p
        while hi < len(e) - 1 and e[hi] > e[p] * 0.5 and hi - p < 0.02 * sr:
            hi += 1
        out.append({'t': float(p / sr), 'ratio_db': float(r[p]), 'level_db': float(20 * np.log10(e[p] + 1e-9)),
                    'width_ms': float((hi - lo) / sr * 1000)})
    return out


def _db(x):
    return 20 * math.log10(max(float(x), 1e-9))


def _highpassed(y, sr, hp=5000.0):
    from scipy import signal
    return signal.sosfilt(signal.butter(4, min(hp, sr / 2 * 0.8), 'hp', fs=sr, output='sos'),
                          np.asarray(y, dtype=np.float64))


def sample_hf_peak_db(path):
    """Peak of a sound's own 5 kHz-and-up part, in dBFS: the click as the detector's clean reading sees it."""
    import soundfile as sf
    y, sr = sf.read(str(path), always_2d=True)
    return _db(np.abs(_highpassed(y.mean(axis=1), sr)).max())


def _segment(y, sr, a, b):
    return y[max(0, int(a * sr)):max(0, int(b * sr))]


def _centroid(seg, sr):
    if len(seg) < 16:
        return None
    s = seg * np.hanning(len(seg))
    spectrum = np.abs(np.fft.rfft(s))
    f = np.fft.rfftfreq(len(s), 1 / sr)
    return float((spectrum * f).sum() / max(spectrum.sum(), 1e-12))


def _decay_ms(y, sr, t):
    seg = np.abs(_segment(y, sr, t, t + 0.5))
    if len(seg) < 8:
        return None
    w = max(1, int(0.002 * sr))
    e = np.sqrt(np.convolve(seg ** 2, np.ones(w) / w, 'same'))
    i = int(e.argmax())
    j = i
    while j < len(e) - 1 and e[j] > e[i] * 0.1:
        j += 1
    return float((j - i) / sr * 1000)


def _chance(times, impulses, lo, hi, duration, draws=200, seed=7):
    """Share of random moments (same count as times) with an impulse in [t+lo, t+hi]."""
    if not len(times) or not impulses:
        return 0.0
    rng = np.random.default_rng(seed)
    it = np.array(sorted(x['t'] for x in impulses))
    share = []
    for _ in range(draws):
        pts = rng.uniform(0.3, max(0.31, duration - 0.3), len(times))
        a = np.searchsorted(it, pts + lo)
        b = np.searchsorted(it, pts + hi)
        share.append(float(np.mean(b > a)))
    return float(np.mean(share))


def _times(rows, key=None):
    out = []
    for r in rows or []:
        if isinstance(r, dict):
            v = r.get(key or 't', r.get('s', r.get('start')))
        else:
            v = r
        if v is not None:
            out.append(float(v))
    return sorted(out)


def analyse(path, voice_dbfs, cuts, words=(), arrivals=(), flashes=(), duration=None, stem=True):
    """Measure picture-synced clicks in a reference's non-voice sound (path: a WAV, ideally the separated music and
    effects). cuts, flashes, arrivals: seconds (or {t}); words: transcript rows ({s}). stem=False: the file still has
    speech in it, so only the clicks on transitions are measured."""
    import soundfile as sf
    y, sr = sf.read(str(path), always_2d=True)
    y = y.mean(axis=1)
    duration = float(duration or len(y) / sr)
    cut_t = _times(cuts)
    flash_t = _times(flashes)
    transitions = sorted(cut_t + [f for f in flash_t if all(abs(f - c) > 0.25 for c in cut_t)])
    imp = detect_impulses(y, sr)
    hf = _highpassed(y, sr)       # the clean reading: music has little up here, so a click's own level shows
    out = {'format': FORMAT, 'stem': bool(stem)}
    # ---- a click on each transition: an impulse starting within -30..+150 ms of the cut
    LO, HI = -0.03, 0.15
    if transitions:
        hits, offsets, peaks, cents, pairs, gaps, decays, clean = [], [], [], [], [], [], [], []
        for c in transitions:
            near = [x for x in imp if c + LO <= x['t'] <= c + HI and x['ratio_db'] >= 18]
            if not near:
                continue
            first = min(near, key=lambda x: x['t'])
            hits.append(c)
            offsets.append(first['t'] - c)
            peaks.append(_db(np.abs(_segment(y, sr, c - 0.003, c + 0.15)).max()) - voice_dbfs)
            clean.append(_db(np.abs(_segment(hf, sr, c - 0.003, c + 0.15)).max()) - voice_dbfs)
            ce = _centroid(_segment(y, sr, c, c + 0.05), sr)
            if ce:
                cents.append(ce)
            d = _decay_ms(y, sr, c)
            if d is not None:
                decays.append(d)
            later = [x for x in imp if first['t'] + 0.04 <= x['t'] <= first['t'] + 0.14]
            pairs.append(bool(later))
            if later:
                gaps.append(min(later, key=lambda x: x['t'])['t'] - first['t'])
        share = len(hits) / len(transitions)
        chance = _chance(transitions, [x for x in imp if x['ratio_db'] >= 18], LO, HI, duration)
        out['transition_click'] = {
            'trigger': 'transition', 'transitions': len(transitions), 'with_click': len(hits),
            'share': round(share, 3), 'chance': round(chance, 3),
            'confirmed': bool(len(hits) >= 3 and share >= chance + 0.25),
            'offset_s': round(float(np.median(offsets)), 3) if offsets else None,
            'offset_range_s': [round(min(offsets), 3), round(max(offsets), 3)] if offsets else None,
            'peak_over_voice_db': round(float(np.median(peaks)), 1) if peaks else None,
            'hf_peak_over_voice_db': round(float(np.median(clean)), 1) if clean else None,
            'centroid_hz': round(float(np.median(cents))) if cents else None,
            'decay_ms': round(float(np.median(decays))) if decays else None,
            'double_click_share': round(sum(pairs) / len(pairs), 3) if pairs else None,
            'double_click_gap_s': round(float(np.median(gaps)), 3) if gaps else None,
            'window_s': [LO, HI]}
    # ---- a quiet tick on each word / caption arrival
    marks = _times(arrivals) or _times(words, 's')
    if marks and stem:
        WLO, WHI = -0.03, 0.06
        busy = [c + k for c in transitions for k in (-0.05, 0.2)]
        away = [m for m in marks if all(not (c - 0.05 <= m <= c + 0.2) for c in transitions)]
        del busy
        quiet = [x for x in imp if all(not (c - 0.05 <= x['t'] <= c + 0.2) for c in transitions)]
        hit_rows = []
        for m in away:
            near = [x for x in quiet if m + WLO <= x['t'] <= m + WHI]
            if near:
                hit_rows.append((m, min(near, key=lambda x: abs(x['t'] - m))))
        share = len(hit_rows) / len(away) if away else 0.0
        chance = _chance(away, quiet, WLO, WHI, duration)
        sharp = [(m, x) for m, x in hit_rows if x['ratio_db'] >= 22 and abs(x['t'] - m) <= 0.02]
        peaks = [_db(np.abs(_segment(y, sr, x['t'] - 0.01, x['t'] + 0.03)).max()) - voice_dbfs for _, x in sharp]
        clean = [_db(np.abs(_segment(hf, sr, x['t'] - 0.01, x['t'] + 0.03)).max()) - voice_dbfs for _, x in sharp]
        cents = [c for c in (_centroid(_segment(y, sr, x['t'] - 0.002, x['t'] + 0.01), sr) for _, x in sharp) if c]
        out['word_click'] = {
            'trigger': 'caption_word', 'arrivals': len(away), 'with_click': len(hit_rows),
            'share': round(share, 3), 'chance': round(chance, 3),
            'confirmed': bool(len(hit_rows) >= 8 and share >= chance + 0.25),
            'clear_examples': len(sharp),
            'offset_s': round(float(np.median([x['t'] - m for m, x in sharp])), 3) if sharp else None,
            'peak_over_voice_db': round(float(np.median(peaks)), 1) if peaks else None,
            'hf_peak_over_voice_db': round(float(np.median(clean)), 1) if clean else None,
            'centroid_hz': round(float(np.median(cents))) if cents else None,
            'window_s': [WLO, WHI],
            'width_ms': round(float(np.median([x['width_ms'] for _, x in sharp])), 2) if sharp else None}
    elif marks:
        out['word_click'] = {'trigger': 'caption_word', 'confirmed': False,
                             'unmeasured': 'speech was not separated from the effects'}
    out['method'] = ('clicks are spikes of 5 kHz-and-up energy about a millisecond wide, 14 dB or more over the local '
                     'median, in the non-voice sound; share = moments with a click in the window; chance = the same '
                     'count of random moments')
    out['limits'] = ['Under speech and music a quiet tick can hide: an unconfirmed count means not heard in the '
                     'stems, not absent.',
                     'Levels are peaks of the non-voice sound against the voice RMS; the timbre needs listening.',
                     'peak_over_voice_db includes the music under the click, so it cannot fall below the music itself; '
                     'hf_peak_over_voice_db is the peak of the 5 kHz-and-up part, where the click shows by itself.']
    return out


def validate(block):
    if not isinstance(block, dict) or block.get('format') != FORMAT:
        raise ValueError('synced sounds must be a letitedit-synced-sounds/1 block')
    for key in ROLES:
        rule = block.get(key)
        if rule is None:
            continue
        if not isinstance(rule, dict):
            raise ValueError(f'synced sound {key} must be an object')
        for name in ('offset_s', 'peak_over_voice_db', 'hf_peak_over_voice_db', 'min_gap_s'):
            value = rule.get(name)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise ValueError(f'synced sound {key}.{name} must be a finite number')
        if rule.get('use') is not None and type(rule['use']) is not bool:
            raise ValueError(f'synced sound {key}.use must be true or false')
    return block


# ------------------------------------------------------------------ placing them in a project

def _tracks_like(script, pattern):
    import re
    return [t for t in script['tracks'] if re.search(pattern, t['name'], re.I)]


def cutaway_transitions(script, every_cut=False):
    """[(time, 'in'|'out')] where a cutaway starts or ends on the main picture; with every_cut, also every join of
    the main track's clips that come from different places."""
    from letitedit.timeline.edit_sync import layout, main_track
    out = []
    for t in _tracks_like(script, r'b-?roll|cutaway'):
        if (t.get('kind') or 'video') != 'video':
            continue
        for it, s, e in layout(t):
            if 'clip' not in it and 'image' not in it and 'motion' not in it:
                continue
            out.append((round(s, 3), 'in'))
            out.append((round(e, 3), 'out'))
    if every_cut:
        main = main_track(script)
        if main is not None:
            last = None
            for it, s, e in layout(main):
                if 'clip' not in it:
                    continue
                if last is not None and (abs(last[1] - s) < 0.04):
                    out.append((round(s, 3), 'cut'))
                last = (it, e)
    return sorted(out)


def caption_arrivals(script):
    """Timeline seconds where a caption word appears: the timed words of kinetic-caption items and the start of
    each text caption item. The two layers of an inverted-then-white caption count once."""
    from letitedit.looks.sound_targets import caption_events
    marks = [round(event['t'], 3) for event in caption_events(script)]
    out = []
    for m in marks:
        if not out or m - out[-1] > 0.02:
            out.append(m)
    return out


def resolve_sound(ref):
    """The file and timing facts of a library sound ('library/camera-shutter_click_04', a file path, ...)."""
    import letitedit.catalogs.assets as assets
    entry = assets.find('id:' + ref if '/' in str(ref) and ':' not in str(ref) else ref, kind='sfx')
    path = Path(assets.abspath(entry['file']))
    if not path.is_file():
        raise ValueError(f'sound {ref!r}: the file is missing ({path})')
    return {'path': str(path), 'peak_db': float(entry.get('peak_db', -3.0)), 'peak_s': float(entry.get('peak_s', 0.0)),
            'onset_s': float(entry.get('onset_s', 0.0)), 'duration_s': float(entry.get('duration_s', 0.3)),
            'hf_peak_db': _hf_peak_cached(str(path))}


_HF = {}


def _hf_peak_cached(path):
    if path not in _HF:
        try:
            _HF[path] = sample_hf_peak_db(path)
        except Exception:  # noqa: BLE001 - unreadable here: the plan falls back to the full-band peak
            _HF[path] = None
    return _HF[path]


def sound_gain_db(rule, snd, voice_dbfs, default_over):
    """Gain that puts this sound at the Look's level against the speech RMS: its 5 kHz-and-up peak at
    hf_peak_over_voice_db (music cannot hide that reading) and its full peak at peak_over_voice_db; where a rule has
    both, the quieter of the two gains, so neither reading goes over its level."""
    gains = []
    hf = rule.get('hf_peak_over_voice_db')
    if hf is not None and snd.get('hf_peak_db') is not None:
        gains.append((voice_dbfs + float(hf)) - snd['hf_peak_db'])
    if rule.get('peak_over_voice_db') is not None or not gains:
        over = float(rule.get('peak_over_voice_db') if rule.get('peak_over_voice_db') is not None else default_over)
        gains.append((voice_dbfs + over) - snd['peak_db'])
    return round(min(gains), 2)


def speech_rms_dbfs(script, max_s=90.0):
    """RMS of the speech on the main track, in dBFS, from its source clips (the level the sounds are set against; the
    export's loudness step moves speech and sounds together). Frames of 30 ms count as speech when they stand within
    25 dB of the loudest tenth. None when nothing can be read."""
    import subprocess
    from letitedit.timeline.edit_sync import layout, main_track
    main = main_track(script)
    if main is None:
        return None
    try:
        import letitedit.pictures.vfx_items as vfx_items
        ffmpeg = str(vfx_items.made.ffmpeg_exe())
    except Exception:  # noqa: BLE001
        return None
    frames, taken = [], 0.0
    for it, start, end in layout(main):
        clip = it.get('clip')
        if not clip or taken >= max_s:
            continue
        length = min(end - start, max_s - taken) * float(it.get('speed', 1.0))
        try:
            raw = subprocess.run([ffmpeg, '-v', 'error', '-ss', str(float(it.get('in', 0))), '-t', f'{length:.3f}',
                                  '-i', str(clip), '-vn', '-ac', '1', '-ar', '16000', '-f', 'f32le', '-'],
                                 capture_output=True, timeout=120).stdout
        except Exception:  # noqa: BLE001
            continue
        y = np.frombuffer(raw, dtype=np.float32)
        n = len(y) // 480
        if n:
            frames.append((y[:n * 480].reshape(n, 480) ** 2).mean(axis=1))
        taken += end - start
    if not frames:
        return None
    power = np.concatenate(frames)
    top = np.percentile(power, 90)
    speech = power[power >= top * 10 ** (-25 / 10)]
    if not len(speech) or top <= 0:
        return None
    return round(10 * math.log10(float(speech.mean()) + 1e-12), 1)


def thin(times, min_gap_s, keep=None):
    """The moments kept when none may sit closer than min_gap_s to the one before; keep(t) forces a moment in."""
    kept = []
    for t in sorted(times):
        if kept and t - kept[-1] < min_gap_s - 1e-9:
            continue
        kept.append(t)
    return kept


def plan(script, rules=None, voice_dbfs=-18.3, transitions='cutaways', roles=('transition_click', 'word_click'),
         sounds=None, total=None):
    """The {kind: sfx} items that put the picture-synced sounds into a project.

    rules: a Look's synced block ({'transition_click': {...}, 'word_click': {...}}) or None for plain defaults.
    voice_dbfs: the speech's RMS level in the mix, in dBFS (the levels are set against it).
    Returns {'items': [...], 'counts': {...}, 'skipped': [...]}."""
    from letitedit.looks import sound_targets
    from letitedit.review import dense
    events, _ = dense.events(script)
    rules = rules or {}
    sounds = {**DEFAULT_SOUNDS, **(sounds or {})}
    items, skipped, counts = [], [], {}
    taken = []
    end = float(total) if total else None
    # --- the click on each transition
    if 'transition_click' in roles:
        rule = rules.get('transition_click') or {}
        if rule.get('use') is False or (rule.get('use') is None and rules and not rule.get('confirmed')):
            skipped.append('transition click: the Look leaves it out' if rule.get('use') is False
                           else 'transition click: measured but not confirmed in the reference (set use: true to place it)')
        else:
            offset = float(rule.get('offset_s') if rule.get('offset_s') is not None else 0.0)
            gap = float(rule.get('min_gap_s') or 0.35)
            moments = cutaway_transitions(script, every_cut=(transitions == 'all_cuts'))
            times = thin([t for t, _ in moments], gap)
            refs = sounds['transition_click']
            made = 0
            for n, t in enumerate(times):
                if end is not None and t > end - 0.2:
                    continue
                snd = resolve_sound(refs[n % len(refs)])
                gain = sound_gain_db(rule, snd, voice_dbfs, 0.0)
                edge = next(edge for time, edge in moments if time == t)
                target = min((event for event in events if event['kind'] == edge),
                             key=lambda event: abs(event['t'] - t), default=None)
                items.append({'kind': 'sfx', 'at': round(t + offset, 3), 'sfx': snd['path'],
                              'sfx_offset_s': round(-snd['peak_s'], 3), 'sfx_gain_db': gain,
                              'sound_target': sound_targets.target_for(target) if target else {'kind': edge, 'at': t},
                              'trigger': 'transition click', '_exact': True})
                taken.append(t + offset)
                made += 1
            counts['transition_click'] = made
    # --- the tick on each caption word
    if 'word_click' in roles:
        rule = rules.get('word_click') or {}
        if rule.get('use') is False or (rule.get('use') is None and rules and not rule.get('confirmed')):
            skipped.append('word click: the Look leaves it out' if rule.get('use') is False
                           else 'word click: not heard in the reference stems (set use: true to place it)')
        else:
            offset = float(rule.get('offset_s') if rule.get('offset_s') is not None else 0.0)
            gap = float(rule.get('min_gap_s') or 0.18)
            marks = caption_arrivals(script)
            if not marks:
                skipped.append('word click: no caption words on the timeline yet; place captions first')
            refs = sounds['word_click']
            made = 0
            last = -9.0
            for n, t in enumerate(marks):
                if t - last < gap - 1e-9:
                    continue
                if any(abs(t - c) < 0.12 for c in taken):
                    continue
                if end is not None and t > end - 0.2:
                    continue
                snd = resolve_sound(refs[n % len(refs)])
                # +-1 dB between neighbours so a run of ticks is not a machine
                wobble = (-1.0, 0.0, 1.0, 0.0)[n % 4]
                gain = round(sound_gain_db(rule, snd, voice_dbfs, -6.0) + wobble, 2)
                target = min((event for event in events if event['kind'] == 'caption_word'),
                             key=lambda event: abs(event['t'] - t))
                items.append({'kind': 'sfx', 'at': round(t + offset, 3), 'sfx': snd['path'],
                              'sfx_offset_s': round(-snd['peak_s'], 3), 'sfx_gain_db': gain,
                              'sound_target': sound_targets.target_for(target),
                              'trigger': 'caption word', '_exact': True})
                last = t
                made += 1
            counts['word_click'] = made
    items.sort(key=lambda x: x['at'])
    return {'items': items, 'counts': counts, 'skipped': skipped}


def rules_for(script, look=None):
    """The synced-sound rules of a Look (its sound.json 'synced' block): the named Look, else the project's chosen one."""
    import json
    import letitedit.looks.looks as looks
    if not look:
        try:
            import letitedit.looks.look_inputs as look_inputs
            chosen = look_inputs.read(script.get('project')) or {}
            look = chosen.get('look')
        except Exception:  # noqa: BLE001 - no brief or no Look chosen: plain defaults
            look = None
    if not look:
        return {}
    card = looks.read(look)
    path = Path(card['recipe']).with_name('sound.json')
    if not path.is_file():
        return {}
    block = json.loads(path.read_text(encoding='utf-8-sig')).get('synced') or {}
    return validate(block) if block else {}


def plan_for_op(script, spec, total=None):
    """plan() for {op: fx, sync_sounds: true | {look?, rules?, voice_dbfs?, transitions?, roles?}}."""
    spec = {} if spec is True else dict(spec or {})
    extra = sorted(set(spec) - {'look', 'rules', 'voice_dbfs', 'transitions', 'roles', 'sounds'})
    if extra:
        raise ValueError(f"fx sync_sounds: unknown {', '.join(extra)}; use look, rules, voice_dbfs, transitions "
                         f"(cutaways | all_cuts), roles, sounds")
    transitions = spec.get('transitions', 'cutaways')
    if transitions not in ('cutaways', 'all_cuts'):
        raise ValueError("fx sync_sounds: transitions is cutaways or all_cuts")
    rules = spec.get('rules')
    if rules is None:
        rules = rules_for(script, spec.get('look'))
    voice = spec.get('voice_dbfs')
    if voice is not None and (type(voice) not in (int, float) or not -60 <= voice <= -3):
        raise ValueError('fx sync_sounds: voice_dbfs is the speech RMS in dBFS, between -60 and -3')
    roles = tuple(spec.get('roles') or ('transition_click', 'word_click'))
    bad = [r for r in roles if r not in ROLES]
    if bad:
        raise ValueError(f"fx sync_sounds: roles are {', '.join(ROLES)}")
    measured = None
    if voice is None:
        measured = speech_rms_dbfs(script)
        if measured is not None and not -60 <= measured <= -3:
            measured = None
    result = plan(script, rules, (-18.3 if measured is None else measured) if voice is None else float(voice),
                  transitions, roles, spec.get('sounds'), total)
    result['voice_dbfs'] = {'value': -18.3 if measured is None else measured if voice is None else float(voice),
                            'from': 'given' if voice is not None else 'measured from the speaker clips'
                            if measured is not None else 'default'}
    return result
