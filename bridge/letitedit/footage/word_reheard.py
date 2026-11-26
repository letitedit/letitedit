"""A word the transcript stretched over seconds has often swallowed other words: a restart ("without the LLM, without risking" came back as
'without' 4.9 s and 'risking' 2.2 s), so the words and times there are wrong. Heard by itself, that stretch comes back right.

runs(words)                 runs of stretched words next to each other
listen(path, run, next_s)   hears one run by itself: its words, or None when nothing better came back
overlay(path, words, hear)  words with each stretched run replaced by what it was heard to say; every other word is the same object

Only a stretched run changes, and only in what this returns: speech.words and its cache, and so captions and cuts by word, stay as they are.
Results are kept per file in CACHE/reheard/<identity>.json, so a run is heard once."""
from __future__ import annotations

import json
import re
import tempfile
import threading
from pathlib import Path

import letitedit.footage.speech as speech

TAIL_S = 1.0        # sound after the run heard with it: a word heard to its end is heard better, and what falls there is thrown away
PAD_S = 0.3         # sound before the first burst, whose quiet start the level misses
MIN_GAP_S = 0.5     # a silence this long inside a run starts a new stretch to hear
MIN_BURST_S = 0.2   # a scrap shorter than this is the tail of the word before
KEEP_NEAR_S = 0.25  # a word heard must lie this close to measured sound, or it's made up
WIDER_S = 2.0       # the second listen takes this much more sound on each side
VERSION = 2
_lock = threading.Lock()


def runs(words):
    out, cur = [], []
    for w in words:
        if speech.stretched(w):
            cur.append(w)
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _file(path):
    return speech.CACHE / 'reheard' / f'{speech._identity(str(path))}.json'


def _load(path):
    try:
        data = json.loads(_file(path).read_text(encoding='utf-8-sig'))
        return data.get('runs', {}) if data.get('version') == VERSION else {}
    except (OSError, ValueError):
        return {}


def _key(run):
    return f"{float(run[0]['s']):.3f}-{float(run[-1]['e']):.3f}"


def _stretches(spans, a, b):
    """The parts of a run worth hearing: (start, end) split at its long silences, scraps left out."""
    parts = []
    for s0, e0 in spans:
        if parts and s0 - parts[-1][1] < MIN_GAP_S:
            parts[-1][1] = e0
        else:
            parts.append([s0, e0])
    return [(max(a, s0 - PAD_S), e0) for s0, e0 in parts if e0 - s0 >= MIN_BURST_S]


def _plain(text):
    return re.sub(r"[^\w']+", '', str(text)).lower()


def _backed_up(heard, wider):
    """Every word heard is also heard, in the same order, when the stretch is heard with the sound around it: a different window of sound, so
    a word the model made up from a few bursts of noise doesn't come back."""
    it = iter(_plain(w['w']) for w in wider)
    return all(any(_plain(h['w']) == x for x in it) for h in heard)


def _hear(path, start, length):
    """(words, engine) for a window of a file. A PC rendering for someone else isn't waited for: the CPU's model if this PC has it, else
    None, which leaves the stretch as it was this time and hears it on a later call."""
    import letitedit.core.render_lock as render_lock
    i = render_lock.info()
    if not i.get('held') or i.get('stale') or render_lock.lock_held_by(i.get('text') or '', render_lock.ancestors()):
        return speech._transcribe(str(path), start, length)
    if not _cpu_model_here():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / 'a.wav'
        if not speech._extract(str(path), wav, start, length):
            return [], 'no-audio'
        got = speech._transcribe_cpu_now(wav)
    return [dict(w, s=round(w['s'] + start, 3), e=round(w['e'] + start, 3)) for w in got], speech.MODEL


def _cpu_model_here():
    try:
        from faster_whisper.utils import download_model
        download_model(speech.MODEL, local_files_only=True)
        return True
    except Exception:  # noqa: BLE001 - not on this PC: nothing is downloaded for this
        return False


def listen(path, run, next_s=None):
    """[{'w','s','e','p','reheard':True}] heard in this run. [] when the sound or the model gives nothing better: stay as it was. None when it
    couldn't be heard right now, so it's tried again later."""
    a, b = float(run[0]['s']), float(run[-1]['e'])
    spans = speech.bursts(path, a, b)
    parts = _stretches(spans, a, b)
    if not parts:
        return []
    out = []
    for s0, e0 in parts:
        end = min(e0 + TAIL_S, b + TAIL_S)
        got = _hear(path, round(s0, 3), round(end - s0, 3))
        if got is None:
            return None
        for w in got[0]:
            if float(w['s']) >= b - 0.02 or float(w['s']) >= e0 + 0.05:        # past the run: the next word's, heard for context
                continue
            if not any(float(w['s']) - KEEP_NEAR_S < y and float(w['e']) + KEEP_NEAR_S > x for x, y in spans):
                continue
            out.append({'w': w['w'], 's': float(w['s']), 'e': round(min(float(w['e']), next_s) if next_s else float(w['e']), 3),
                        'p': w.get('p', 1.0), 'reheard': True})
    if not out:
        return []
    # the run's last word sits in a scrap too short to hear by itself: it's still there, where that scrap is
    last = run[-1]
    if _plain(last['w']) not in {_plain(w['w']) for w in out}:
        after = [(x, y) for x, y in spans if x >= out[-1]['e'] - 0.05]
        if after:
            out.append({'w': last['w'], 's': float(after[-1][0]), 'e': float(after[-1][1]), 'p': last.get('p', 1.0), 'reheard': True})
    wider = _hear(path, round(max(0.0, a - WIDER_S), 3), round(b - a + 2 * WIDER_S, 3))
    if wider is None:
        return None
    if not _backed_up(out, wider[0]):
        return []
    if [_plain(w['w']) for w in out] == [_plain(w['w']) for w in run]:     # the same words: heard alone they come back with a capital
        out = [dict(h, w=w['w']) for h, w in zip(out, run)]
    return out


def overlay(path, words, start=None, end=None, hear=False):
    """`words` (speech.words or cached_words on this file, for start to end) with each stretched run replaced by what it was heard to say. hear=False
    uses only what's already been heard. A file with no stretched word, or a run heard to say nothing, gives the same words back."""
    if not words:
        return words
    full = speech.cached_words(str(path))
    all_runs = runs(full or [])
    if not all_runs:
        return words
    known = _load(path)
    changed = False
    index = {id(w): i for i, w in enumerate(full)}
    asked = {(w['w'], float(w['s']), float(w['e'])) for w in words}
    lo, hi = float(words[0]['s']) if start is None else float(start), float('inf') if end is None else float(end)
    swaps = {}
    for run in all_runs:
        here = any((w['w'], float(w['s']), float(w['e'])) in asked for w in run)             or (float(run[0]['s']) < hi and float(run[-1]['e']) > lo)   # the range lies inside a run that starts before it
        if not here:
            continue
        key = _key(run)
        if key not in known and hear:
            last = index[id(run[-1])]
            next_s = float(full[last + 1]['s']) if last + 1 < len(full) else None
            heard = listen(path, run, next_s)
            if heard is not None:           # None: couldn't be heard right now; asked again next time
                known[key] = heard
                changed = True
        if known.get(key):
            swaps[index[id(run[0])]] = (index[id(run[-1])], known[key])
    if changed:
        with _lock:
            f = _file(path)
            f.parent.mkdir(parents=True, exist_ok=True)
            merged = {**_load(path), **known}
            f.write_text(json.dumps({'version': VERSION, 'runs': merged}, ensure_ascii=False), encoding='utf-8')
    if not swaps:
        return words
    drop = {i for first, (last, _) in swaps.items() for i in range(first, last + 1)}
    dropped = {(full[i]['w'], float(full[i]['s']), float(full[i]['e'])) for i in drop}
    out = [w for w in words if (w['w'], float(w['s']), float(w['e'])) not in dropped]
    for first, (last, heard) in swaps.items():
        out += [dict(w) for w in heard if lo - 1e-6 <= float(w['s']) < hi]
    out.sort(key=lambda w: float(w['s']))
    return out
