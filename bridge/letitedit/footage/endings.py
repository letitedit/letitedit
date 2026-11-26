"""Does the last line of a video sound like a finished thought?  Measured on the source the last clip comes from.

    ending(path, out, ws=None) -> {'word', 'runs_on', 'next_gap', 'next_word', 'fall_st', 'voiced', 'open', 'said'}

Signals, from what is already installed (no Praat; the pitch is prosody.pitch's numpy YIN tracker):
  * the words: the source carries straight on after the cut (the next word within RUNS_ON_S of the last word's
    sound, and the last word has no sentence end);
  * the pitch: over the last word, how far the voice falls from its earlier part to its last 80 ms (semitones).
    Only the words flag an ending. Measured on IMG_0017 (one low, creaky voice) neither pitch nor the energy after the
cut separated an unfinished end from a finished one ("this." and "edits." both fall about the same; more sound follows
the cut after "edits." than after "this."), so both are reported (`fall_st`, `sound_after`) and neither flags.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import re
import subprocess

import numpy as np

RUNS_ON_S = 0.35        # the source's next word starts this soon after the last word's sound: it keeps going
FALL_MIN_ST = 1.5       # a final fall smaller than this (semitones) is level
CARRY_S = 0.25         # speech-level sound within this long after the cut counts as the speech carrying on
MIN_VOICED = 12         # voiced 10 ms frames in the last WINDOW_S needed to say anything about the pitch
WINDOW_S = 0.5          # the stretch of the last word (and the sound before it) the pitch is read over
LAST_N = 6              # its 'end': the last this-many voiced frames, against all the voiced frames before them
GOODBYE_AFTER_S = 30.0  # a sign-off that starts this soon after the cut was the talk's own close, left out
GOODBYE_BEFORE_S = 20.0 # a sign-off already in the cut's last this-many seconds: the cut has its goodbye
SIGN_OFF = re.compile(
    r"\b(?:good ?bye|bye(?: bye)?|take care|until next time|see (?:you|ya) (?:(?:guys|all|everyone|everybody) )?"
    r"(?:later|next|soon|then|tomorrow|in the next)"
    r"|(?:thanks|thank you)(?: so much)?(?: (?:guys|all|everyone|everybody))? for (?:watching|listening|tuning in|joining)"
    r"|that's (?:all|it) for (?:today|now|this))\b")

def _audio16(path, a, b):
    import letitedit.timeline.cutpoints as cutpoints
    r = subprocess.run([cutpoints.FFMPEG, '-v', 'error', '-ss', f'{max(0.0, a):.3f}', '-t', f'{b - a:.3f}', '-i', str(path),
                        '-vn', '-ac', '1', '-ar', '16000', '-f', 's16le', '-'], capture_output=True,
                       creationflags=cutpoints.NO_WINDOW)
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float64) / 32768.0


def sound_after(path, t, within=CARRY_S):
    """Seconds from a cut at source time t to speech-level sound that is still going or begins again right after it
    (30 ms average at least TAIL_OVER_DB over that clip's room floor), or None when the next `within` seconds are
    at the floor. 0.0 = the cut lands while the sound is still decaying."""
    import letitedit.timeline.cutpoints as cutpoints
    t0, env = cutpoints._envelope(path, t - 1.5, t + 1.5)
    if len(env) < 40:
        return None
    floor = float(np.percentile(env, 10))
    loud = np.convolve(env, np.ones(3) / 3, mode='same') > floor + cutpoints.TAIL_OVER_DB
    k = int(round((t - t0) / cutpoints.HOP))
    seg = np.flatnonzero(loud[k:k + int(round(within / cutpoints.HOP)) + 1])
    return round(float(seg[0]) * cutpoints.HOP, 2) if len(seg) else None


def ending(path, out, ws=None):
    """The ending of a clip that stops at source time `out`, or None when no word is said just before it."""
    import letitedit.timing.prosody as prosody
    import letitedit.footage.speech as speech
    ws = ws if ws is not None else speech.sound_words(path, out - 3, out + 3, cached=True)
    if not ws:
        return None
    done = [(i, w) for i, w in enumerate(ws) if w['s'] < out - 0.02]
    if not done:
        return None
    i, w = done[-1]
    end = min(w['e'], out)
    nxt = ws[i + 1] if i + 1 < len(ws) else None
    gap = None if nxt is None else round(nxt['s'] - w['e'], 2)
    sentence_end = w['w'].strip()[-1:] in '.?!'
    runs_on = gap is not None and gap < RUNS_ON_S and not sentence_end
    # source words after the cut that carry the thought on (said for the plain words of the check)
    said_next = ' '.join(x['w'].strip() for x in ws[i + 1:i + 5]) if nxt else ''
    # pitch over the last word: its last voiced sounds against the voiced sound of the 0.5 s before
    a0 = max(0.0, end - 1.2)
    x = _audio16(path, a0, end + 0.1)
    fall = None
    voiced = 0
    if len(x) > 1600:
        f0, _ = prosody.pitch(x, method='yin')
        k = lambda t: int(round((t - a0) / 0.01))
        v = f0[k(end - WINDOW_S):k(end) + 5]
        v = v[np.isfinite(v)]
        voiced = int(len(v))
        if voiced >= MIN_VOICED:
            fall = round(float(12 * np.log2(np.median(v[-LAST_N:]) / np.median(v[:-LAST_N]))), 1)
    level = fall is not None and -fall < FALL_MIN_ST
    carry = sound_after(path, out)
    return {'word': w['w'].strip(), 'at': round(end, 2), 'runs_on': runs_on, 'next_gap': gap, 'next_word': said_next,
            'fall_st': fall, 'voiced': voiced, 'level': level, 'sound_after': carry, 'open': bool(runs_on),
            'sentence_end': sentence_end}


def describe(e):
    """One plain sentence on what was heard, for a finding (only the words signal flags; pitch is added as a hint)."""
    out = (f"in the source the next word (\"{e['next_word'].split(' ')[0]}\") follows {e['next_gap']:.2f} s after "
           f"\"{e['word']}\" with no sentence end, so the thought carries on past the cut")
    if e['fall_st'] is not None:
        out += f"; the pitch on the last word moves {e['fall_st']:+.1f} semitones (a weak hint)"
    return out


def _token(word):
    return re.sub(r"[^\w']", '', str(word).lower().replace('\u2019', "'"))


def _sign_off(ws):
    """The index into ws of the word a sign-off phrase starts on, and the phrase, or None."""
    tokens = [_token(w['w']) for w in ws]
    text, starts = '', []
    for t in tokens:
        starts.append(len(text))
        text += t + ' '
    m = SIGN_OFF.search(text)
    if not m:
        return None
    i = max(k for k, at in enumerate(starts) if at <= m.start())
    return i, m.group(0).strip()


def goodbye(ws, out):
    """The source's own goodbye left out after a cut at source time `out` (ws: the source's words around it, each
    {'w', 's', 'e'}): {'after_s': seconds from the cut to the sign-off, 'said': the words from the cut through the
    sign-off, 'phrase'}, or None when no sign-off starts within GOODBYE_AFTER_S or the cut's own last
    GOODBYE_BEFORE_S already hold one."""
    before = [w for w in ws if out - GOODBYE_BEFORE_S <= w['s'] < out - 0.02]
    if _sign_off(before):
        return None
    after = [w for w in ws if out - 0.02 <= w['s'] <= out + GOODBYE_AFTER_S]
    hit = _sign_off(after)
    if not hit:
        return None
    i, phrase = hit
    end = min(len(after), i + len(phrase.split()))
    while end < len(after) and _token(after[end]['w']) in ('bye', 'goodbye') and after[end]['s'] - after[end - 1]['e'] < 1:
        end += 1
    return {'after_s': round(after[i]['s'] - out, 1), 'phrase': phrase, 'ends_at': round(after[end - 1]['e'], 2),
            'said': ' '.join(w['w'].strip() for w in after[:end])}
