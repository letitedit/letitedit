"""The settings, small helpers and the thresholds.

Part of `music_sync` (letitedit/timing/music_sync.py), which imports every name here back,
so `music_sync.X` is the same object it always was.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
import numpy as np
HERE = _paths.BRIDGE
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge
CACHE_ROOT = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache')))
THRESHOLDS_FILE = HERE / 'timing_thresholds.json'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

LANE = 'music'
LANE_VERSION = 3   # 2: T72, a song added when posting counts; 3: the beat finder is the only one
SONG_VERSION = 2           # bump when song_grid changes (part of its cache name)
SCHEMA_VERSION = 1
SR = 22050                 # analysis sample rate
BT_FPS = 50.0              # Beat This! frames per second (hop 441 at 22.05 kHz)
CHECKPOINT = 'final0'
LAG_LO, LAG_HI = int(60 * BT_FPS / 230), int(60 * BT_FPS / 38)       # beat periods searched: 38-230 bpm

MUSIC_NAME = re.compile(r'music|song|score|bed', re.I)
SFX_NAME = re.compile(r'sfx|\bfx\b|effect|sound|foley|whoosh|hit', re.I)
VOICE_NAME = re.compile(r'voice|vo\b|narrat|dialog|speech|interview', re.I)
AUDIO_EXT = {'.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.aiff', '.aif', '.wma'}

# the lane's own settings (timing_signals.lane_settings merges the caller's on top)
DEFAULTS = {
    'stem': 'auto',             # videos: auto (separate the music when someone talks) | separate | mix
    'energy_every_s': 0.5,      # the lane's energy series step
    'level_every_s': 0.1,       # the lane's level series step (music as heard)
    'beats_per_bar': None,      # None: 3 or 4 per song from the downbeat probability; or force 2/3/4/6
    'music_audio_min_s': 8.0,   # an audio-only file on a non-music, non-effects track counts as music from this length
    'audible_db': -50.0,        # a beat whose music is quieter than this (dBFS, K-weighted) is marked not audible
}

# thresholds this module owns (keys 'sync.' in timing_thresholds.json; merged in, never overwriting others' keys)
THRESHOLDS = {
    'sync.on_beat_frames': {'value': 1.0, 'unit': 'frames', 'about': 'an event at most this far from a beat (either '
                            'side) is counted as on the beat (monotony runs, on-beat share)'},
    'sync.near_beat_frames': {'value': 2.0, 'unit': 'frames', 'about': 'the second, looser share reported'},
    'sync.monotony_share': {'value': 0.7, 'unit': 'share of cuts', 'about': 'an on-beat share of cuts at or above '
                            'this is reported as possibly mechanical (every cut on the beat); reported with its number, '
                            'not judged'},
    'sync.monotony_run': {'value': 8, 'unit': 'cuts', 'about': 'a run of this many consecutive on-beat cuts is reported '
                          'as a long run'},
    'sync.hard_hit_sound_lead_frames': {'value': 0.5, 'unit': 'frames', 'about': 'reference, not a rule (AOTC Dune, '
                                        'letitedit-sound): on a hard hit the sound sits about half a frame before the cut'},
    'sync.hard_hit_min_strength': {'value': 0.6, 'unit': '0-1 onset strength at the beat (song percentile scale)',
                                   'about': 'a downbeat or phrase start at least this strong counts as a hard hit when a '
                                   'cut lands within sync.near_beat_frames of it'},
    'sync.beat_clear_min': {'value': 0.75, 'unit': 'mean Beat This! beat probability at the beats', 'about':
                            'beat_quality clear at or above this (synthetic and clear songs 0.75-1.0; songs without a '
                            'steady beat about 0.5)'},
    'sync.beat_weak_min': {'value': 0.45, 'unit': 'mean Beat This! beat probability at the beats', 'about':
                           'beat_quality weak at or above this, none below'},
    'sync.gap_min_s': {'value': 1.0, 'unit': 's', 'about': 'speech gaps (between the padded words) shorter than this '
                       'are not checked for a music swell'},
    'sync.swell_rise_db': {'value': 3.0, 'unit': 'dB', 'about': 'the music level in a speech gap this much above its '
                           'level under the words around it counts as rising in the pause'},
    'sync.music_under_speech_db': {'value': 10.0, 'unit': 'dB', 'about': 'music closer than this to the dialogue '
                                   'loudness under words is listed (reference: the score op sits music 18 dB under)'},
    'sync.sfx_window_frames': {'value': 6, 'unit': 'frames', 'about': 'a motion peak or cut within this of an SFX '
                               'onset is taken as the impact it belongs to'},
    'sync.sfx_match_frames': {'value': 2, 'unit': 'frames', 'about': 'an SFX onset within this of its impact counts '
                              'as on the impact'},
    'sync.section_match_bars': {'value': 1.0, 'unit': 'bars', 'about': 'a story boundary within this many bars of a '
                                'song boundary (section, phrase start, drop or join) counts as aligned'},
    'sync.motion_peak_rel': {'value': 2.0, 'unit': 'x the median of the shot', 'about': 'fallback motion peaks (when '
                             'the motion lanes are not registered): residual frame difference at least this many times '
                             'the shot median'},
}


# ============================================================================ small helpers

def _r(x, nd=3):
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if math.isfinite(v) else None


def _clock(s):
    s = max(0.0, float(s))
    return f'{int(s // 60)}:{s % 60:05.2f}'


def _hash(obj, n=16):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:n]


def _clean(x, nd=None):
    """JSON-safe: numpy -> Python, NaN/inf -> None, optionally rounded."""
    if isinstance(x, np.ndarray):
        x = x.tolist()
    elif isinstance(x, np.generic):
        x = x.item()
    if isinstance(x, float):
        if not math.isfinite(x):
            return None
        return round(x, nd) if nd is not None else x
    if isinstance(x, dict):
        return {str(k): _clean(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v, nd) for v in x]
    if isinstance(x, Path):
        return str(x)
    return x


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'{path.name}.{os.getpid()}-{threading.get_ident()}.tmp')
    tmp.write_text(json.dumps(_clean(data), separators=(',', ':')), encoding='utf-8')
    for _ in range(30):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05)
    tmp.unlink(missing_ok=True)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None


def _file_key(path):
    """Content key of a file (size + hash of its first 2 MB, as footage notes) + its modification time."""
    st = os.stat(path)
    h = hashlib.sha1()
    with open(path, 'rb') as fh:
        h.update(fh.read(2 * 1024 * 1024))
    return f'{st.st_size}-{h.hexdigest()[:16]}-{st.st_mtime_ns % 10 ** 12}'


def _decode(path, sr=SR, start=None, dur=None):
    """Mono float32 audio at sr via ffmpeg (start/dur in seconds)."""
    ff = Path(os.environ.get('LETITEDIT_APP', (_SAI_ROOT + '\\app'))) / 'ffmpeg.exe'
    args = [str(ff), '-v', 'error', '-nostdin']
    if start:
        args += ['-ss', f'{float(start):.4f}']
    if dur:
        args += ['-t', f'{float(dur):.4f}']
    args += ['-i', str(path), '-vn', '-sn', '-dn', '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-']
    r = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW)
    data = r.stdout[:len(r.stdout) // 4 * 4]
    return np.frombuffer(data, np.float32).copy()


# ============================================================================ thresholds

_TH = {'mtime': None, 'data': {}}


def _thresholds_file():
    try:
        m = THRESHOLDS_FILE.stat().st_mtime_ns
    except OSError:
        return {}
    if _TH['mtime'] != m:
        try:
            _TH['data'] = json.loads(THRESHOLDS_FILE.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            _TH['data'] = {}
        _TH['mtime'] = m
    return _TH['data']


def th(name, given=None):
    """A threshold's value: the caller's (options 'thresholds': {name or short name: value}), else the shared file,
    else this module's default."""
    short = name.split('.', 1)[-1]
    for k in (name, short):
        if given and k in given and given[k] is not None:
            return given[k]
    v = _thresholds_file().get(name)
    if isinstance(v, dict) and 'value' in v:
        return v['value']
    if v is not None:
        return v
    d = THRESHOLDS.get(name) or TRAJECTORY_DEFAULTS.get(name)
    return d['value'] if isinstance(d, dict) else d


def used_thresholds(prefix, given=None, table=None):
    table = table or THRESHOLDS
    return {k: {'value': th(k, given), 'unit': v.get('unit'), 'about': v.get('about')}
            for k, v in table.items() if k.startswith(prefix)}


def merge_thresholds(entries, path=None):
    """Add the given keys to timing_thresholds.json without touching any other key (re-read right before the atomic
    write; retried when another writer got in between). Keys already present keep their value."""
    path = Path(path or THRESHOLDS_FILE)
    for _ in range(30):
        try:
            before = path.read_text(encoding='utf-8-sig') if path.exists() else '{}'
            data = json.loads(before or '{}')
        except ValueError:
            raise RuntimeError(f'{path} is not valid JSON; not overwriting it') from None
        added = {k: v for k, v in entries.items() if k not in data}
        if not added:
            return data
        data.update(added)
        tmp = path.with_name(f'{path.name}.{os.getpid()}-{threading.get_ident()}.tmp')
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + '\n', encoding='utf-8')
        now = path.read_text(encoding='utf-8') if path.exists() else '{}'
        if now != before:
            tmp.unlink(missing_ok=True)
            continue
        try:
            os.replace(tmp, path)
            return data
        except PermissionError:
            tmp.unlink(missing_ok=True)
            time.sleep(0.05)
    raise RuntimeError(f'could not update {path}')


# trajectory.py's thresholds live there; th() falls back to them through this name (filled at its import)
TRAJECTORY_DEFAULTS = {}
