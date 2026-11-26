"""The lightest check that still catches a video that is broken (T80, Turbo): measured, free, a few seconds, no AI.

check(video) -> {'ok': bool, 'problems': [plain sentences], 'notes': [...], 'facts': {...}}
It looks at the finished file only:
  - a picture: sampled frames are not black (the first, the last and half of them), the file's length is what was asked for;
  - a sound: there is an audio stream and it isn't silent (mean level);
  - faces: a face is found in N of the sampled frames (a note, because only a talking-head video should have one: a person
    reading the report decides whether 0 of 6 means a covered face).
It cannot tell a clipped word, a covered cap, a wrong claim or a bad cut: Turbo says so in its message."""
import json
import re
import subprocess
import tempfile
from pathlib import Path

import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (no console windows)
import letitedit.review.checks as checks

NO_WINDOW = 0x08000000
SAMPLES = 6
BLACK = 6.0          # mean luma (0-255) under this is a black frame
SILENT_DB = -55.0    # mean level under this is no sound


def _run(args, timeout=120):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, encoding='utf-8', errors='replace',
                          timeout=timeout, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)


def _probe(video):
    r = _run([checks.FFPROBE, '-v', 'error', '-show_entries', 'format=duration:stream=codec_type,duration', '-of', 'json', video])
    data = json.loads(r.stdout or '{}')
    kinds = [s.get('codec_type') for s in data.get('streams', [])]
    return float(data.get('format', {}).get('duration') or 0), kinds


def _sound_level(video):
    r = _run([checks.FFMPEG, '-hide_banner', '-nostats', '-i', video, '-vn', '-af', 'volumedetect', '-f', 'null', '-'])
    mean = re.search(r'mean_volume:\s*(-?[\d.]+|-inf) dB', r.stderr or '')
    peak = re.search(r'max_volume:\s*(-?[\d.]+|-inf) dB', r.stderr or '')

    def num(m):
        return None if not m else (-120.0 if m.group(1) == '-inf' else float(m.group(1)))
    return num(mean), num(peak)


def check(video, expect_seconds=None):
    from PIL import Image
    import numpy as np
    video = str(video)
    problems, notes, facts = [], [], {}
    duration, kinds = _probe(video)
    facts['duration_s'] = round(duration, 2)
    if 'video' not in kinds or duration <= 0:
        return {'ok': False, 'problems': ['The file has no picture.'], 'notes': [], 'facts': facts}
    if expect_seconds and abs(duration - expect_seconds) > max(0.6, 0.02 * expect_seconds):
        problems.append(f'The video is {duration:.1f} s but the timeline is {expect_seconds:.1f} s: it is cut short or runs on.')
    # sound
    if 'audio' not in kinds:
        problems.append('The video has no sound track.')
    else:
        mean, peak = _sound_level(video)
        facts['sound_mean_db'], facts['sound_peak_db'] = mean, peak
        if mean is None or mean < SILENT_DB:
            problems.append('The sound is silent (nothing audible in the whole video).')
    # picture and faces, from frames
    times = [min(0.2, duration / 4)] + [duration * k / (SAMPLES - 1) for k in range(1, SAMPLES - 1)] + [max(0.0, duration - 0.3)]
    lumas, faces = [], 0
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(times):
            png = Path(tmp) / f'f{i}.png'
            _run([checks.FFMPEG, '-v', 'error', '-y', '-ss', f'{t:.2f}', '-i', video, '-frames:v', '1', '-vf', 'scale=540:-2', png])
            if not png.exists():
                lumas.append(None)
                continue
            lumas.append(float(np.asarray(Image.open(png).convert('L'), np.float32).mean()))
            try:
                if checks.faces_in(png, width=540):
                    faces += 1
            except Exception:  # noqa: BLE001 - faces are a note; never a reason to fail
                pass
    seen = [x for x in lumas if x is not None]
    facts['sampled_frames'] = len(seen)
    facts['faces_in_frames'] = faces
    facts['lumas'] = [None if x is None else round(x, 1) for x in lumas]
    if not seen:
        problems.append('No frame could be read from the video.')
    else:
        black = [x is not None and x < BLACK for x in lumas]
        if lumas[0] is not None and black[0]:
            problems.append('The video opens on a black frame.')
        if lumas[-1] is not None and black[-1]:
            problems.append('The video ends on a black frame (a missing end).')
        if sum(black) >= len(seen) / 2:
            problems.append(f'{sum(black)} of {len(seen)} sampled frames are black.')
    notes.append(f'A face is in {faces} of {len(seen)} sampled frames.' + (
        ' If this is a talking-head video, a face may be covered or missing.' if seen and faces == 0 else ''))
    return {'ok': not problems, 'problems': problems, 'notes': notes, 'facts': facts,
            'covers': 'picture not black, length, a sound that is not silent, faces counted; not clipped words, cut edges, '
                      'captions against a face, the mix or what is said'}
