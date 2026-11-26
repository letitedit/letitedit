"""The settings and the small helpers (times, decoding).

Part of `soundtrack` (letitedit/sound/soundtrack.py), which imports every name here back,
so `soundtrack.X` is the same object it always was.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
import hashlib
import json
import os
import subprocess
import threading
import time
from pathlib import Path
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache')))
WORK = CACHE / 'soundtrack'
SCHEMA = 'letitedit-soundtrack/1'
ANALYSIS_VERSION = 6
PLAN_VERSION = 1
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
SR = 22050                  # analysis sample rate
MSR = 48000                 # measurement sample rate
N_FFT, HOP = 2048, 512      # analysis frames (23 ms)

ENERGY_WORDS = {'low': 0.2, 'mid': 0.55, 'medium': 0.55, 'high': 0.9}
HIT_KINDS = ('downbeat', 'bar', 'phrase', 'drop', 'beat')
APPROACHES = ('auto', 'natural', 'join', 'stretch', 'break', 'none')
PROTECT_MODES = ('duck_deep', 'drop_out')
ENDINGS = ('auto', 'song', 'fade', 'stop')
ENTRIES = ('fade', 'hard')
MODES = ('plan', 'apply', 'measure', 'song')

# music levels: dB relative to the dialogue's loudness (the song is first brought to the dialogue's loudness), like
# the score op; 'none' is a stretch with no section energy asked for. duck_deep is dB under the natural sound of the
# protected range (measured from the footage), or under the dialogue when that can't be measured.
LEVELS = {'talk': -18.0, 'none': -6.0, 'low': -9.0, 'mid': -6.5, 'high': -4.0, 'duck_deep': -20.0}
OPTIONS = {
    'crossfade_s': 0.1,            # crossfade at a join on the beat grid (rounded to whole frames, at least 2); it
                                   # ends on the bar line, so the incoming downbeat is at full level
    'weak_crossfade_s': 0.15,      # ... when the beat is weak
    'coarse_crossfade_s': 1.5,     # ... when the song has no steady beat
    'fade_in_s': 1.5,              # music start (entry 'fade')
    'fade_out_s': 3.0,             # music end (ending 'fade')
    'drop_fade_out_s': 1.0,        # before a drop_out range (the music is gone when it starts)
    'drop_fade_in_s': 0.5,         # after a drop_out range
    'break_fade_s': 0.1,           # the music stopping before a hit
    'tolerance_ms': 25.0,          # a hit the grid already lands within this needs no edit
    'attack_s': 0.35, 'preroll_s': 0.1, 'hold_s': 0.3, 'release_s': 1.0,   # dips under speech (as Add music)
    'merge_gap_s': 4.0,            # speech pauses shorter than this stay dipped (no pumping)
    'section_ramp_s': 1.0,         # level change between sections (a hit makes it instant)
    'duck': True,                  # dip under speech
    'beats_per_bar': 4,
    'beam': 96,                    # beam width of the material search
    'min_run_s': 2.0,              # shorter stretches of music between drop-outs are left silent
    'peak_ceiling_dbfs': -2.0,     # the music on its own stays under this (sample peak of the song + gain)
    'correct_engine_offsets': True,  # after applying: pieces the render plays off time by over half a frame (a
                                   # song file the engine seeks imprecisely) get their in points shifted, measured again
    'preview_audio': True,         # write an mp3 of the planned music bed (for listening; the project is not used)
    'match_placed_loudness': False,  # bring the song to the dialogue by the loudness of the bars placed, not the
                                   # whole song's (a level matched to a measured reference: its louder or quieter
                                   # passages otherwise move the whole bed by the difference: 1.2 dB on one
                                   # measured learned-Look soundtrack)
}
REPEAT = {'max_uses': None, 'min_gap_s': 20.0, 'loops': False, 'loop_bars': 8}

_MEM = {}
_LOCK = threading.Lock()


# ============================================================================ small helpers

def _sec(v, what='time'):
    """Seconds from a number or 'm:ss.s' / 'h:mm:ss'."""
    if v is None:
        return None
    if isinstance(v, bool):
        raise ValueError(f'{what}: {v!r} is not a time')
    if isinstance(v, (int, float)):
        return float(v)
    text = str(v).strip()
    try:
        if ':' in text:
            s = 0.0
            for part in text.split(':'):
                s = s * 60 + float(part)
            return s
        return float(text)
    except ValueError:
        raise ValueError(f'{what}: {v!r} is not a time (seconds, or "m:ss.s")') from None


def _r(x, nd=3):
    return None if x is None else round(float(x), nd)


def _ms(x):
    return None if x is None else round(float(x) * 1000.0, 1)


def _clock(t):
    t = round(max(0.0, float(t)), 1)
    return f'{int(t // 60)}:{t - 60 * int(t // 60):04.1f}'


def _span(a, b):
    return f'{_clock(a)}-{_clock(b)}'


def _hash(obj, n=12):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:n]


def _file_id(path):
    st = os.stat(path)
    return {'path': str(Path(path).resolve()), 'size': st.st_size, 'mtime_ns': st.st_mtime_ns}


def _json_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'{path.stem}.{os.getpid()}-{threading.get_ident()}.tmp')
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, separators=(',', ':'))
    for _ in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05)
    tmp.unlink(missing_ok=True)


def _decode(path, sr, channels=1):
    import letitedit.sound.av_tools as av_tools
    return av_tools._decode(path, sr, channels)
