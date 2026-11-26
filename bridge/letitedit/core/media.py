"""Video and audio files through the bundled ffmpeg and ffprobe (in the install folder's app\\).

    ffmpeg(), ffprobe()                 the programs' paths (LETITEDIT_ROOT honoured, read each call)
    probe(path)                         ffprobe's format and streams, as a dict (90 s limit)
    audio_streams(path)                 how many audio streams a file has; UnreadableMedia when it can't be read
    UnreadableMedia, unreadable(path, what, detail)
                                        a file that couldn't be read or decoded just now (a cloud drive offline, a file
                                        still syncing, a damaged file): nothing measured from such a read is cached
    verify_video(path, duration=None, profile=None)
                                        an export's checks: a video stream, the length within 0.15 s, the project's size,
                                        frame rate and scan, and a full decode; raises ValueError or RuntimeError on a
                                        failure, else returns what it measured
"""
from __future__ import annotations

import json
from pathlib import Path

from . import paths
from .proc import run_tool


def ffmpeg():
    return Path(paths.install_root()) / 'app' / 'ffmpeg.exe'


def ffprobe():
    return Path(paths.install_root()) / 'app' / 'ffprobe.exe'


class UnreadableMedia(OSError):
    """A media file that could not be read or decoded just now. Nothing measured from that read is cached, so asking
    again reads the file again."""


def unreadable(path, what='it', detail=''):
    """An UnreadableMedia saying so in plain words (what: 'the sound', 'the picture' ...)."""
    tail = (detail or '').strip()
    tail = f' ({tail[-300:]})' if tail else ''
    return UnreadableMedia(f"Couldn't read {what} of {Path(str(path)).name} just now{tail}. Nothing from this read was "
                           'saved, so asking again reads it again (a file on a cloud drive may be offline or still syncing).')


def audio_streams(path):
    """How many audio streams the file has (0: it has no sound track). Raises UnreadableMedia when ffprobe can't read
    the file."""
    import subprocess
    r = subprocess.run([str(ffprobe()), '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index',
                        '-of', 'csv=p=0', str(path)], capture_output=True, text=True, errors='replace', timeout=90,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if r.returncode != 0:
        raise unreadable(path, 'the file', r.stderr)
    return len([line for line in r.stdout.splitlines() if line.strip()])


def probe(path):
    return json.loads(run_tool([ffprobe(), '-v', 'error', '-show_format', '-show_streams', '-of', 'json', path],
                               timeout=90))


def verify_video(path, duration=None, profile=None):
    info = probe(path)
    video = next((s for s in info['streams'] if s['codec_type'] == 'video'), None)
    if not video:
        raise ValueError('Export has no video stream')
    actual = float(info['format']['duration'])
    if duration is not None and abs(actual - duration) > .15:
        raise ValueError(f'Duration mismatch: expected {duration}, got {actual}')
    if profile and (video['width'], video['height']) != (profile['width'], profile['height']):
        raise ValueError('Export dimensions do not match project')
    rate_num, rate_den = map(int, video.get('avg_frame_rate', '0/1').split('/'))
    rate = rate_num / rate_den if rate_den else 0
    if profile and profile.get('fps') and abs(rate - profile['fps']) > .001:
        raise ValueError('Export frame rate does not match project')
    if profile and profile.get('progressive') and video.get('field_order') not in ('progressive', 'unknown', None):
        raise ValueError('Progressive project unexpectedly exported interlaced')
    run_tool([ffmpeg(), '-v', 'error', '-xerror', '-i', path, '-f', 'null', '-'])
    return {'duration_s': actual, 'width': video['width'], 'height': video['height'], 'fps': rate,
            'field_order': video.get('field_order'), 'codec': video['codec_name'], 'full_decode_passed': True}
