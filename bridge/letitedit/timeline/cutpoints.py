"""Cut points from words: find a spoken phrase in a source file and cut on the gaps around it.

    find(clip, text, near=None) -> {'in', 'out', 'said', 'others'}   (source seconds)
    snap(clip, start, end, before=None, after=None) -> (in, out)

Word timestamps from speech recognition are often a little early at the end of a word. snap() moves the cut points
out to where the sound actually stops (and starts), measured on the audio, never into the next or previous word.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import difflib
import subprocess
import unicodedata

import numpy as np

FFMPEG = (_SAI_ROOT + '\\app\\ffmpeg.exe')
NO_WINDOW = 0x08000000
RATE = 16000
HOP = 0.01


def _tok(w):
    """A word as phrases are compared: lowercase letters and digits of any script (with their accents and other
    combining marks) and apostrophes; punctuation, symbols and spaces dropped. For English words this is the same as
    keeping only a-z, 0-9 and apostrophes; 'café', 'Straße', 'привет' and '日本語' keep their letters."""
    s = unicodedata.normalize('NFKC', str(w)).lower().replace('’', "'")
    return ''.join(ch for ch in s if ch.isalnum() or ch == "'" or unicodedata.category(ch)[0] == 'M')


def _envelope(path, a, b):
    """Short-time loudness (dB, one value per 10 ms) of the source between a and b seconds."""
    a = max(0.0, a)
    r = subprocess.run([FFMPEG, '-v', 'error', '-ss', f'{a:.3f}', '-t', f'{max(0.05, b - a):.3f}', '-i', str(path), '-vn',
                        '-ac', '1', '-ar', str(RATE), '-f', 's16le', '-'], capture_output=True, creationflags=NO_WINDOW)
    x = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    n = int(RATE * HOP)
    if len(x) < n:
        return a, np.full(1, -90.0)
    frames = x[:len(x) // n * n].reshape(-1, n)
    return a, 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-6)


def snap(path, start, end, before=None, after=None, pad_in=0.03, pad_out=0.06, reach=0.6):
    """(in, out) around speech from start to end, measured on the audio: out where the last word's sound has died
    away, in just before the first word's sound begins. Recognised word edges are often early or late, so the
    neighbouring words' times only limit how far to look; in continuous speech the cut goes to the quietest point
    between the words."""
    lo = max(start - reach, 0.0) if before is None else max(start - reach, before - 0.25, 0.0)
    hi = end + reach if after is None else min(end + reach, after + 0.25)
    t0, env = _envelope(path, lo - 0.3, hi + 0.3)
    if len(env) < 5:
        return round(max(lo, start - pad_in), 3), round(min(hi, end + pad_out), 3)
    idx = lambda t: int(np.clip(round((t - t0) / HOP), 0, len(env) - 1))
    floor = float(np.percentile(env, 15))
    seg = env[idx(start):idx(end) + 1]
    peak = float(np.percentile(seg, 90)) if len(seg) else floor + 20
    thresh = floor + max(4.0, 0.3 * (peak - floor))
    quiet = 6   # 60 ms below the threshold counts as the sound having stopped

    def first_quiet(k, stop, step):
        run = 0
        while (k < stop if step > 0 else k > stop):
            run = run + 1 if env[k] <= thresh else 0
            if run >= quiet:
                return k - step * (quiet - 1)
            k += step
        return None

    k = first_quiet(idx(max(start, end - 0.05)), idx(hi), 1)
    if k is None:   # no pause: the quietest moment just after the word
        a, b = idx(end - 0.1), idx(min(hi, end + 0.25))
        k = a + int(np.argmin(env[a:b + 1])) if b > a else idx(end)
        out = t0 + k * HOP
    else:
        out = t0 + k * HOP + pad_out
    k = first_quiet(idx(min(end, start + 0.05)), idx(lo), -1)
    if k is None:
        a, b = idx(max(lo, start - 0.25)), idx(start + 0.1)
        k = a + int(np.argmin(env[a:b + 1])) if b > a else idx(start)
        cut_in = t0 + k * HOP
    else:
        cut_in = t0 + k * HOP - pad_in
    cut_in, out = round(max(0.0, min(cut_in, start)), 3), round(max(out, end), 3)
    # A quiet point picked from an envelope can still sit inside a softly spoken word.
    # Keep the selected phrase and move only to a clean point before/after it.
    cin = safe_edge(path, cut_in, 'in', reach=reach)
    cout = safe_edge(path, out, 'out', reach=reach)
    if cin['clean'] and cin['at'] <= start and (before is None or cin['at'] > before):
        cut_in = cin['at']
    if cout['clean'] and cout['at'] >= end and (after is None or cout['at'] < after):
        out = cout['at']
    return round(cut_in, 3), round(out, 3)


def safe_edge(path, t, side, reach=0.5):
    """A cut point checked against cached speech and measured sound; prefer a natural handle."""
    import letitedit.footage.speech as speech
    ws = speech.sound_words(path, t - 1, t + 1, cached=True) or []
    word = cut_inside_word(ws, t, side, path)
    sound = cut_in_sound(path, t, side, reach=reach)
    tail = cut_in_tail(path, ws, t, side)
    if word is None and sound is None and tail is None:
        return {'at': round(t, 3), 'clean': True, 'word': None, 'sound': False}
    candidates = []
    if tail:   # the word's real tail / soft opening (word_tail), a little clear of it
        candidates.append(tail['tail'] + 0.04 if side == 'out' else tail['tail'] - 0.03)
    if word:
        edge = word.get('voiced', (word['s'], word['e']))
        candidates.append((edge[0] - 0.05) if side == 'in' else (edge[1] + 0.08))
    if sound:
        for key in ('earlier', 'later'):
            if sound[key] is not None:
                candidates.append(sound[key])
    tail_at = None if not tail else max(0.0, candidates[0])
    candidates = [max(0.0, x) for x in candidates if abs(x - t) <= reach or x == tail_at]
    # An in point uses the pause before the word; an out point uses the one after it.
    direction = [x for x in candidates if (x <= t if side == 'in' else x >= t)]
    for x in sorted(direction, reverse=(side == 'in')):
        if (cut_inside_word(ws, x, side, path) is None and cut_in_sound(path, x, side, reach=0) is None
                and cut_in_tail(path, ws, x, side) is None):
            return {'at': round(x, 3), 'clean': True, 'word': word['w'] if word else (tail['w'] if tail else None),
                    'sound': bool(sound), 'tail': bool(tail)}
    return {'at': round(t, 3), 'clean': False, 'word': word['w'] if word else (tail['w'] if tail else None),
            'sound': bool(sound), 'tail': bool(tail)}


EDGE_REACH_OUT_S = 0.6    # clean_edge: how far a cut may move outward (taking in the rest of a word, its tail or soft opening)
EDGE_REACH_IN_S = 0.35    # ... and inward (dropping the clipped part of a word: never more than about one word)
GAP_MIN_S = 0.03          # a gap between two recognised words at least this long is a place between words
BOUNDARY_SLACK_S = 0.04   # words that touch: their quietest moment is looked for this far either side of the boundary
WORD_MIN_S = 0.06          # a recognised "word" shorter than this is a sliver (a repeated "and and"), not a word to keep
LOCAL_S = 0.1             # in a longer pause between words, the quietest moment within this of the cut


def _changes_words(ws, t, x):
    """True when moving a cut from t to x would add or drop a whole word other than the one t is inside: the
    passage's words stay what the editor chose (only the clipped word is kept whole or dropped)."""
    lo, hi = min(t, x), max(t, x)
    for w in ws:
        if w['s'] + BOUNDARY_SLACK_S < t < w['e'] - BOUNDARY_SLACK_S or w['e'] - w['s'] < WORD_MIN_S:
            continue        # the clipped word itself (not just its recognised edge), or a recogniser's sliver
        mid = (w['s'] + w['e']) / 2
        if lo < mid < hi:
            return True
    return False


def edge_problem(path, ws, t, side):
    """What a cut at source time t goes through, measured the way the review's project check does: 'word' (a
    word's voiced sound carries on through it), 'tail' (a word's tail or soft opening is clipped), 'sound' (the
    sound on both sides is over the speech threshold), or None (a clean place to cut)."""
    if cut_inside_word(ws, t, side, path) is not None:
        return 'word'
    if cut_in_tail(path, ws, t, side) is not None:
        return 'tail'
    if cut_in_sound(path, t, side, reach=0) is not None:
        return 'sound'
    return None


def gap_quietest(path, ws, t, reach=0.5):
    """The gaps between recognised words near t, each with its quietest 10 ms moment near t:
    [{'at', 'after', 'before', 'from', 'to'}] nearest first ('after' / 'before' are the words either side)."""
    ws = sorted((w for w in ws if w.get('e', 0) > w.get('s', 0)), key=lambda w: w['s'])
    spans = []
    for a, b in zip(ws, ws[1:]):
        lo_, hi_ = min(a['e'], b['s']), max(a['e'], b['s'])
        if hi_ - lo_ < GAP_MIN_S:        # words that touch: their boundary, give or take a recogniser's slack
            lo_, hi_ = lo_ - BOUNDARY_SLACK_S, hi_ + BOUNDARY_SLACK_S
        if hi_ >= t - reach and lo_ <= t + reach:
            spans.append((a, b, lo_, hi_))
    if not spans:
        return []
    t0, env = _envelope(path, min(x[2] for x in spans) - 0.05, max(x[3] for x in spans) + 0.05)
    out = []
    for a, b, lo_, hi_ in spans:
        # the quietest moment near t (a long pause keeps the length the editor chose: within LOCAL_S of t, or of
        # the pause's nearer end when t is outside it)
        near = min(max(t, lo_), hi_)
        ka = int(round((max(lo_, near - LOCAL_S) - t0) / HOP))
        kb = int(round((min(hi_, near + LOCAL_S) - t0) / HOP))
        ka, kb = max(0, ka), min(len(env) - 1, kb)
        k = ka + int(np.argmin(env[ka:kb + 1])) if kb >= ka else ka
        out.append({'at': round(t0 + k * HOP, 3), 'after': a['w'], 'before': b['w'], 'from': round(lo_, 3),
                    'to': round(hi_, 3), 'level_db': float(env[k]) if len(env) else None})
    return sorted(out, key=lambda g: abs(g['at'] - t))


FRAME_REACH = 2           # T362 (fps given): whole frames looked at either side of the clean place
QUIET_FRAME = 'trim_quiet_frame'          # T362's switch (settings.json); LETITEDIT_TRIM_QUIET_FRAME (1 or 0) wins
QUIET_FRAME_ENV = 'LETITEDIT_TRIM_QUIET_FRAME'


def quiet_frame():
    """Whether a clip edge's clean place is found on whole frames (clean_edge's fps; default on)."""
    import os
    forced = os.environ.get(QUIET_FRAME_ENV, '').strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    try:
        import letitedit.core.hardware as hardware
        return hardware.settings().get(QUIET_FRAME) is not False
    except Exception:  # noqa: BLE001 - an unreadable setting means the default: on
        return True


def clean_edge(path, t, side, reach_out=EDGE_REACH_OUT_S, reach_in=EDGE_REACH_IN_S, ws=None, fps=None):
    """The nearest clean place for a clip edge at source time t (side 'in' or 'out'), measured with the same rules
    the review's project check uses (edge_problem). Candidates: the edges of the clipped word's sound (keeping the
    whole word, or dropping the clipped part of it), a word's real tail or soft opening, the nearest pauses, and the
    quietest moment of each gap between recognised words. An edge moves at most reach_out outward (later for an out
    point, earlier for an in point) and reach_in inward. When no clean place is that close (the words, or a sound
    under them, run on), it goes to the quietest moment between two words, so no word is cut.
    fps (T362, trim_quiet_frame): the place is a whole frame of the clip at that rate, where the cut really lands
    (a clip's edge plays to a frame: the 10 ms quietest moment between two frames is measured again on the frame the
    engine cuts at): t is measured on its own frame, and the clean frame nearest the place found (FRAME_REACH frames
    either side, the frame after it first for an out point) is taken, else the frame nearest it.
    Returns {'at', 'moved', 'clean', 'how', 'problem' (what the original edge went through, or None), 'word'}."""
    import letitedit.footage.speech as speech
    if ws is None:
        ws = speech.sound_words(path, t - 1.5, t + 1.5, cached=True) or []
    ws = sorted(ws, key=lambda word: word['s'])
    if not fps:
        return _clean_edge(path, t, side, reach_out, reach_in, ws)
    fps = float(fps)
    t = round(t * fps) / fps                 # the frame the engine cuts at
    e = _clean_edge(path, t, side, reach_out, reach_in, ws)
    return _on_a_frame(path, ws, t, side, e, fps, reach_out, reach_in)


def _on_a_frame(path, ws, t, side, e, fps, reach_out, reach_in):
    """clean_edge's place `e` for an edge at frame time t, on a whole frame (clean_edge's fps)."""
    outward = (lambda x: x > t) if side == 'out' else (lambda x: x < t)
    if e['clean'] and abs(e['at'] - t) < 1e-6:
        return {**e, 'at': round(t, 4)}            # t's own frame is clean
    base = e['at'] if (e['clean'] or e.get('between_words')) else t
    k0 = round(base * fps)
    later_first = side == 'out'
    frames = sorted({k0 + d for d in range(-FRAME_REACH, FRAME_REACH + 1)},
                    key=lambda k: (abs(k / fps - base), 0 if (k / fps >= base) == later_first else 1))

    def allowed(x):
        return x >= 0 and abs(x - t) <= (reach_out if outward(x) else reach_in) + 1e-9 and not _changes_words(ws, t, x)
    for k in frames:
        x = k / fps
        if abs(x - t) < 1e-6:
            continue                               # t's own frame: measured above
        if allowed(x) and edge_problem(path, ws, x, side) is None:
            how = e['how'] if e['clean'] else e['how'].split(', at their quietest moment')[0] + ', where it is quiet'
            return {**e, 'at': round(x, 4), 'moved': round(x - t, 4), 'clean': True, 'between_words': False,
                    'how': f'{how} (the whole frame at {x:.3f})'}
    if not (e['clean'] or e.get('between_words')):
        return {**e, 'at': round(t, 4)}
    x = k0 / fps
    if abs(x - t) < 1e-6 or not allowed(x):
        return {**e, 'at': round(t, 4), 'moved': 0.0}
    return {**e, 'at': round(x, 4), 'moved': round(x - t, 4), 'how': f"{e['how']} (the whole frame at {x:.3f})"}


def _clean_edge(path, t, side, reach_out, reach_in, ws):
    """clean_edge's search at source time t, ws sorted (no frame grid)."""
    for index, word in enumerate(ws):
        boundary = word['e'] if side == 'out' else word['s']
        if abs(t - boundary) > .02:
            continue
        limit = (ws[index + 1]['s'] if index + 1 < len(ws) else None) if side == 'out' else (
            ws[index - 1]['e'] if index else None)
        tail = word_tail(path, boundary, limit, side)
        if tail is None:
            return {'at': round(t, 3), 'moved': 0.0, 'clean': False, 'problem': 'tail',
                    'how': 'next word starts before the decay reaches the room' if side == 'out' else
                           'previous word ends before the soft opening reaches the room', 'word': word['w']}
        target = tail + .04 if side == 'out' else max(0, tail - .03)
        if limit is not None:
            target = min(target, limit) if side == 'out' else max(target, limit)
        if abs(tail - boundary) >= TAIL_MIN_S and abs(target - t) <= reach_out:
            return {'at': round(target, 3), 'moved': round(target - t, 3), 'clean': True, 'problem': 'tail',
                    'how': f'keeps the natural {"tail" if side == "out" else "soft opening"} of "{word["w"]}"',
                    'word': word['w']}
    problem = edge_problem(path, ws, t, side)
    if problem is None:
        return {'at': round(t, 3), 'moved': 0.0, 'clean': True, 'how': 'clean', 'problem': None, 'word': None}
    outward = (lambda x: x > t) if side == 'out' else (lambda x: x < t)

    def allowed(x):
        return x >= 0 and abs(x - t) <= (reach_out if outward(x) else reach_in) + 1e-9 and not _changes_words(ws, t, x)

    cands = {}

    def add(x, how):
        x = round(float(x), 3)
        if allowed(x) and x not in cands:
            cands[x] = how

    word = cut_inside_word(ws, t, side, path)
    if word:
        vs, ve = word.get('voiced', (word['s'], word['e']))
        if side == 'in':
            add(vs - 0.05, f"keeps the whole word \"{word['w'].strip()}\"")
            add(ve + 0.02, f"starts after the clipped word \"{word['w'].strip()}\"")
        else:
            add(ve + 0.08, f"keeps the whole word \"{word['w'].strip()}\"")
            add(vs - 0.03, f"ends before the clipped word \"{word['w'].strip()}\"")
    tail = cut_in_tail(path, ws, t, side)
    if tail:
        add(tail['tail'] + 0.04 if side == 'out' else tail['tail'] - 0.03,
            f"keeps the {'tail' if side == 'out' else 'soft opening'} of \"{tail['w'].strip()}\"")
    for x in quiet_points(path, t, side, reach=max(reach_out, reach_in)):
        add(x, 'in the nearest pause')
    gaps = gap_quietest(path, ws, t, reach=max(reach_out, reach_in))
    for g in gaps:
        add(g['at'], f"between \"{g['after'].strip()}\" and \"{g['before'].strip()}\"")
    clean = []
    for x, how in cands.items():
        p = edge_problem(path, ws, x, side)
        if p is None:
            clean.append((abs(x - t), 0 if outward(x) else 1, x, how))
        elif p == 'tail':        # one step on: past that word's tail too
            tl = cut_in_tail(path, ws, x, side)
            if tl:
                y = round(tl['tail'] + 0.04 if side == 'out' else tl['tail'] - 0.03, 3)
                if allowed(y) and edge_problem(path, ws, y, side) is None:
                    clean.append((abs(y - t), 0 if outward(y) else 1, y, how + ' and its tail'))
    if clean:
        _, _, x, how = min(clean)
        return {'at': x, 'moved': round(x - t, 3), 'clean': True, 'how': how, 'problem': problem,
                'word': word['w'].strip() if word else None}
    # nothing clean that close: the quietest moment between two words, if that cuts no word or tail
    for g in gaps:
        x = g['at']
        if allowed(x) and cut_inside_word(ws, x, side, path) is None and cut_in_tail(path, ws, x, side) is None:
            return {'at': x, 'moved': round(x - t, 3), 'clean': False, 'between_words': True,
                    'how': f"between \"{g['after'].strip()}\" and \"{g['before'].strip()}\", at their quietest moment "
                           f"(a sound runs on under them: no pause within {max(reach_out, reach_in):g} s)",
                    'problem': problem, 'word': word['w'].strip() if word else None}
    return {'at': round(t, 3), 'moved': 0.0, 'clean': False, 'how': 'no clean place near', 'problem': problem,
            'word': word['w'].strip() if word else None}


def word_keeping_pauses(ws, t, sound):
    """The pauses cut_in_sound found near t ('earlier', 'later') that a cut can move to without adding or dropping a
    whole word."""
    return [x for x in ((sound or {}).get('earlier'), (sound or {}).get('later'))
            if x is not None and not _changes_words(ws, t, x)]


def at_quietest_between_words(path, ws, t, tol=0.03):
    """The gap (gap_quietest entry) when t is within tol of the quietest moment between two recognised words, else
    None (or within 1.5 dB of its level): the best place for a cut where the sound runs on."""
    for g in gap_quietest(path, ws, t, reach=0.05):
        if not g['from'] - 1e-6 <= t <= g['to'] + 1e-6:
            continue
        if abs(g['at'] - t) <= tol:
            return g
        t0, env = _envelope(path, t - 0.05, t + 0.05)    # level at t against the quietest moment near it
        k = int(np.clip(round((t - t0) / HOP), 0, len(env) - 1))
        if g.get('level_db') is not None and float(env[k]) - g['level_db'] <= 1.5:
            return g
    return None


def find(path, text, near=None, start=None, end=None):
    """Where `text` is said in a source file: {'in', 'out', 'said', 'at', 'others'}; cut points snapped to the
    gaps around it. near (seconds) picks between repeats; start/end limit the search."""
    import letitedit.footage.speech as speech
    ws = speech.words(path, start, end)
    toks = [_tok(w['w']) for w in ws]
    want = [t for t in (_tok(x) for x in str(text).split()) if t]
    if not want:
        raise ValueError('words: give the phrase to find, e.g. "they put these on tight"')
    if not ws:
        raise ValueError(f'nothing is said in {path} (no words found)')
    n = len(want)
    cands = []
    for size in sorted({n, max(1, n - 1), n + 1}):
        for i in range(0, len(toks) - size + 1):
            r = difflib.SequenceMatcher(None, want, toks[i:i + size]).ratio()
            if r >= 0.6:
                cands.append((r, i, i + size - 1))
    if not cands:
        best = max(((difflib.SequenceMatcher(None, ' '.join(want), ' '.join(toks[i:i + n])).ratio(), i)
                    for i in range(max(1, len(toks) - n + 1))), default=(0, 0))
        i = best[1]
        raise ValueError(f'"{text}" is not said in {path}; closest: "{" ".join(w["w"] for w in ws[i:i + n])}" '
                         f'at {ws[i]["s"]:.2f}s (see letitedit_words)')
    top = max(c[0] for c in cands)
    good = [c for c in cands if c[0] >= top - 1e-9]
    # repeats: the one nearest `near`, else the first
    good.sort(key=lambda c: (abs(ws[c[1]]['s'] - near) if near is not None else ws[c[1]]['s']))
    _, i, j = good[0]
    before = ws[i - 1]['e'] if i > 0 else None
    after = ws[j + 1]['s'] if j + 1 < len(ws) else None
    a, b = snap(path, ws[i]['s'], ws[j]['e'], before, after)
    others = sorted({round(ws[c[1]]['s'], 2) for c in good[1:] if abs(ws[c[1]]['s'] - ws[i]['s']) > 0.5})
    return {'in': a, 'out': b, 'said': ' '.join(w['w'] for w in ws[i:j + 1]), 'match': round(top, 2), 'others': others}


def sounding(path, t):
    """True when there is speech-level sound at source time t (not a pause or room tone)."""
    t0, env = _envelope(path, t - 1.0, t + 1.0)
    if len(env) < 20:
        return True
    floor, peak = float(np.percentile(env, 15)), float(np.percentile(env, 90))
    thresh = floor + max(4.0, 0.3 * (peak - floor))
    k = int(round((t - t0) / HOP))
    return float(np.mean(env[max(0, k - 3):k + 4])) > thresh


SOUND_KEPT_S = 0.04      # a cut goes through a sound when the 40 ms the clip keeps next to it ...
SOUND_GONE_S = 0.06      # ... and the 60 ms it drops are both over the speech threshold
QUIET_RUN_S = 0.04       # a pause at least this long under the threshold is a clean place to cut
SOUND_MIN_DB = 9.0       # ... over the room by at least this much (a breath or a rustle stays under it)


def _quiet_runs(env, thresh, min_frames):
    """[(a, b)] frame runs at or under thresh lasting at least min_frames (b exclusive)."""
    q = np.concatenate([[False], env <= thresh, [False]])
    d = np.diff(q.astype(np.int8))
    return [(a, b) for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)) if b - a >= min_frames]


def cut_in_sound(path, t, side, reach=0.5):
    """The sound a cut at source time t goes through, or None; measured on the audio, with no words (a cut can go
    through an 'um', a laugh or the first sound of a word the transcript times wrongly). side 'out': the clip ends
    at t, keeping the sound before it; 'in': the clip starts at t. It goes through a sound when the SOUND_KEPT_S kept
    next to the cut and the SOUND_GONE_S dropped are both over the speech threshold (the floor (15th percentile of
    10 ms levels within 1.2 s) plus max(SOUND_MIN_DB, 35% of the way to the speech peak (90th percentile))). Returns
    {'kept_db', 'gone_db' (over the floor), 'earlier', 'later'}: the nearest clean cut points within `reach` s each
    way (an out point 60 ms into a quiet run of at least QUIET_RUN_S, an in point 30 ms before its end), None
    where there is no pause that close (the words run on)."""
    t0, env = _envelope(path, t - 1.2, t + 1.2)
    if len(env) < 40:
        return None
    floor, peak = float(np.percentile(env, 15)), float(np.percentile(env, 90))
    thresh = floor + max(SOUND_MIN_DB, 0.35 * (peak - floor))
    k = int(round((t - t0) / HOP))
    nk, ng = int(round(SOUND_KEPT_S / HOP)), int(round(SOUND_GONE_S / HOP))
    kept = env[max(0, k - nk):k] if side == 'out' else env[k:k + nk]
    gone = env[k:k + ng] if side == 'out' else env[max(0, k - ng):k]
    if not len(kept) or not len(gone) or float(np.mean(kept)) <= thresh or float(np.mean(gone)) <= thresh:
        return None
    pts = []
    for a, b in _quiet_runs(env, thresh, max(1, int(round(QUIET_RUN_S / HOP)))):
        mid = (a + b) / 2
        x = min(a + 6, mid) if side == 'out' else max(b - 3, mid)
        pts.append(t0 + x * HOP)
    earlier = max([x for x in pts if t - reach <= x < t], default=None)
    later = min([x for x in pts if t < x <= t + reach], default=None)
    return {'kept_db': round(float(np.mean(kept)) - floor, 1), 'gone_db': round(float(np.mean(gone)) - floor, 1),
            'threshold_db': round(thresh - floor, 1),
            'earlier': round(float(earlier), 2) if earlier is not None else None,
            'later': round(float(later), 2) if later is not None else None}


def quiet_points(path, t, side, reach=0.5):
    """Clean cut points in the pauses within `reach` s of t, by cut_in_sound's measure (an out point 60 ms into a
    quiet run of at least QUIET_RUN_S, an in point 30 ms before its end), nearest first."""
    t0, env = _envelope(path, t - 1.2, t + 1.2)
    if len(env) < 40:
        return []
    floor, peak = float(np.percentile(env, 15)), float(np.percentile(env, 90))
    thresh = floor + max(SOUND_MIN_DB, 0.35 * (peak - floor))
    pts = []
    for a, b in _quiet_runs(env, thresh, max(1, int(round(QUIET_RUN_S / HOP)))):
        mid = (a + b) / 2
        x = t0 + (min(a + 6, mid) if side == 'out' else max(b - 3, mid)) * HOP
        if abs(x - t) <= reach:
            pts.append(round(float(x), 3))
    return sorted(pts, key=lambda x: abs(x - t))


TAIL_OVER_DB = 9.0        # a word's tail / soft opening counts while the sound (30 ms average) is this far over the room's floor
TAIL_BRIDGE_S = 0.25      # ... and a stop's closure (quiet) up to this long does not end it
HEAD_BRIDGE_S = 0.06      # a soft opening has no closure before it: a short quiet before the sound ends the search
TAIL_REACH_S = 0.6        # ... looked for no further than this from the word's recognised edge
TAIL_MIN_S = 0.08         # a cut clips the tail when at least this much of it is dropped


def word_tail(path, end, limit=None, side='out', reach=TAIL_REACH_S):
    """Where the sound of a word really stops, measured on the audio relative to that clip's own room floor (the
    10th percentile of 10 ms levels within 1.5 s). side 'out': scan forward from the word's recognised end `end`,
    past a stop's closure, to the last frame TAIL_OVER_DB over the floor before the sound is back at the floor for
    TAIL_BRIDGE_S; `limit` = the next word's start, never passed. side 'in': the same backward from the word's
    recognised start (soft openings: s, f, h), `limit` = the previous word's end. Returns the time (seconds), or
    `end` itself when the word has no tail, or None when the sound runs on into `limit` (continuous speech: there is
    no tail to measure, the next word is the sound)."""
    lo, hi = end - 1.5, end + 1.5
    t0, env = _envelope(path, lo, hi)
    if len(env) < 40:
        return end
    floor = float(np.percentile(env, 10))
    loud = np.convolve(env, np.ones(3) / 3, mode='same') > floor + TAIL_OVER_DB   # a lone rustle doesn't count
    step = 1 if side == 'out' else -1
    k0 = int(round((end - t0) / HOP))
    k_lim = int(round(((limit if limit is not None else end + step * reach) - t0) / HOP))
    k_lim = min(max(k_lim, 0), len(env) - 1)
    if step > 0:
        k_lim = min(k_lim, k0 + int(round(reach / HOP)))
    else:
        k_lim = max(k_lim, k0 - int(round(reach / HOP)))
    bridge = int(round((TAIL_BRIDGE_S if step > 0 else HEAD_BRIDGE_S) / HOP))
    last, quiet, k = None, 0, k0
    while (k <= k_lim if step > 0 else k >= k_lim) and 0 <= k < len(env):
        if loud[k]:
            last, quiet = k, 0
        else:
            quiet += 1
            if quiet >= bridge:
                break
        k += step
    else:
        # reached the limit without a quiet stretch: the sound runs on into the next word (or the reach)
        if limit is not None and last is not None and abs(last - k_lim) <= 1:
            return None
    if last is None:
        return end
    t = t0 + last * HOP
    return round(max(t, end) if step > 0 else min(t, end), 3)


def cut_in_tail(path, ws, t, side):
    """The word whose tail (or soft opening) a cut at source time t clips, or None. side 'out': the cut is after a
    word's recognised end, but its sound goes on (word_tail) for TAIL_MIN_S or more beyond the cut. side 'in': the
    cut is after the sound of a word's soft opening has begun (before the word's recognised start) and TAIL_MIN_S or
    more of that opening is dropped. Returns {'w', 'tail': the sound's real edge, 'dropped': seconds cut off}."""
    for i, w in enumerate(ws):
        if side == 'out':
            if not (w['e'] - 0.02 <= t < w['e'] + TAIL_REACH_S):
                continue
            nxt = ws[i + 1]['s'] if i + 1 < len(ws) else None
            if nxt is not None and t >= nxt:
                continue
            tail = word_tail(path, w['e'], nxt, 'out')
            if tail is not None and tail - t >= TAIL_MIN_S:
                return {'w': w['w'], 'tail': tail, 'dropped': round(tail - t, 2)}
        else:
            if not (w['s'] - TAIL_REACH_S < t <= w['s'] + 0.02):
                continue
            prv = ws[i - 1]['e'] if i > 0 else None
            if prv is not None and t <= prv:
                continue
            head = word_tail(path, w['s'], prv, 'in')
            if head is not None and t - head >= TAIL_MIN_S:
                return {'w': w['w'], 'tail': head, 'dropped': round(t - head, 2)}
    return None


CLIPPED_MIN_S = 0.08      # voiced sound of a word on each side of a cut before the cut counts as clipping it


def _voiced(path):
    try:
        import letitedit.sound.music as music
        return music.voice_times(path)
    except Exception:  # noqa: BLE001 - no voice detection: fall back to the sound level at the cut
        return None


def _runs(spans, gap=0.1):
    """Voiced spans with gaps shorter than `gap` joined: sound that carries on."""
    out = []
    for x, y in sorted(spans):
        if out and x - out[-1][1] < gap:
            out[-1][1] = max(out[-1][1], y)
        else:
            out.append([x, y])
    return out


def cut_inside_word(ws, t, side, path=None):
    """The word a cut at source time t clips, or None. side: 'out' (end of a clip) or 'in' (start). With the
    source path, a cut counts only when the word's voiced sound carries on through it, with at least
    CLIPPED_MIN_S on each side (recognised word edges often include the pause or the noise next to them); the word
    then carries 'kept' and 'cut' (seconds of that sound on each side) and 'voiced' [start, end] (that sound)."""
    spans = _voiced(path) if path is not None else None
    for w in ws:
        if not w['s'] < t < w['e']:
            continue
        if spans is None:
            hit = (side == 'out' and w['s'] + 0.02 < t < w['e'] - 0.08) or (side == 'in' and w['s'] + 0.08 < t < w['e'] - 0.02)
            if hit and (path is None or sounding(path, t)):
                return w
            continue
        run = next(((x, y) for x, y in _runs(spans) if x < t < y), None)
        if run is None:
            continue                      # the cut is in a pause: the word's recognised span just runs over it
        a, b = max(w['s'], run[0]), min(w['e'], run[1])     # the word's sound that carries on through the cut
        before, after = t - a, b - t
        if min(before, after) < CLIPPED_MIN_S:
            continue
        kept, cut = (before, after) if side == 'out' else (after, before)
        return dict(w, kept=round(kept, 2), cut=round(cut, 2), voiced=[round(a, 2), round(b, 2)])
    return None
