"""Views: pictures and data of footage and timelines.

    look(items, layout, size, per_row, labels, lanes, out_dir)        frames of files and projects side by side, with
                                                                       sound / speech / word lanes under them
    try_changes(project, versions, align, size, frames, render)       versions of an edit, each on its own scratch copy,
                                                                       lined up moment by moment, plus a review MP4
    overview(project, start, end, scale, lanes, width, out_dir)       the whole edit as one timeline picture (or pages)
    stills(source, times, project, region, size, out_dir, format)     frames of a file or project as image files

Images come back as bytes and are also saved as files whose paths are in the result. Every number has a default; the
result reports the value used (and lists the ones left at their default under 'defaults').
Project frames and sound are rendered by melt, the export engine; file frames are decoded by ffmpeg.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import contextlib
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
HERE = _paths.BRIDGE
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import letitedit.review.checks as checks  # noqa: E402
import letitedit.server.core_tools as core_tools  # noqa: E402

FFMPEG = checks.FFMPEG
MELT = checks.MELT
NO_WINDOW = checks.NO_WINDOW
CACHE = checks.CACHE

BG = (24, 24, 28)
LANE_BG = (36, 36, 42)
TEXT = (235, 235, 235)
DIM = (150, 150, 160)
ACCENT = (255, 220, 0)
GAP = 2
PREROLL = 3.0          # seconds of sound rendered before a span, so short-term loudness (3 s window) is full at its start

LOOK_LANES = ('waveform', 'spectrogram', 'loudness', 'speech', 'words')
SOUND_LANES = ('waveform', 'spectrogram', 'loudness')
OVERVIEW_LANES = ('thumbs', 'clips', 'tracks', 'speech', 'words', 'loudness', 'beats', 'graphics', 'captions', 'gaps',
                  'recorded')
OVERVIEW_DEFAULT = ['thumbs', 'clips', 'tracks', 'speech', 'words', 'recorded']
TRY_LANES_DEFAULT = ['loudness', 'words']
LANE_H = {'waveform': 60, 'spectrogram': 90, 'loudness': 70, 'speech': 16, 'words': 36, 'thumbs': 72, 'clips': 40,
          'tracks': 14, 'beats': 24, 'graphics': 30, 'captions': 30, 'gaps': 18, 'recorded': 34}
PALETTE = [(70, 130, 180), (205, 120, 60), (90, 160, 90), (170, 90, 170), (200, 170, 60), (80, 170, 170),
           (190, 80, 90), (120, 120, 200), (150, 110, 70), (110, 170, 120), (200, 110, 150), (130, 150, 60)]
KIND_COLOR = {'graphic': (150, 95, 200), 'caption': (120, 100, 170), 'ass': (150, 95, 200), 'vfx': (60, 160, 160),
              'ffmpeg': (60, 160, 160), 'freeze': (110, 140, 160), 'voice': (160, 140, 90), 'raw': (110, 110, 110)}


# ---------------------------------------------------------------------------- small helpers

def _folder(out_dir, kind):
    if out_dir:
        d = Path(out_dir)
    else:
        d = CACHE / 'views' / kind / f'{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:6]}'
    d.mkdir(parents=True, exist_ok=True)
    return d


_FONTS = {}


def _font(px, bold=False):
    key = (int(px), bool(bold))
    if key not in _FONTS:
        from PIL import ImageFont
        try:
            _FONTS[key] = ImageFont.truetype(r'C:\Windows\Fonts\arialbd.ttf' if bold else r'C:\Windows\Fonts\arial.ttf',
                                             int(px))
        except OSError:
            _FONTS[key] = ImageFont.load_default()
    return _FONTS[key]


def _tw(font, text):
    try:
        return font.getlength(text)
    except AttributeError:
        return 7 * len(text)


def _fit(text, font, width):
    """text cut (with an ellipsis) to fit width px; '' when nothing fits."""
    text = str(text)
    if width < 6:
        return ''
    if _tw(font, text) <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _tw(font, text[:mid] + '…') <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + '…' if lo else ''


def _clock(t, nd=2):
    t = round(max(0.0, float(t)), nd)
    m = int(t // 60)
    s = round(t - 60 * m, nd)
    return f'{m}:{s:0{3 + nd}.{nd}f}' if nd else f'{m}:{int(s):02d}'


def _r(x, nd=3):
    return round(float(x), nd)


def _slug(text):
    return re.sub(r'[^A-Za-z0-9]+', '-', str(text)).strip('-')[:32] or 'version'


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _quiet(cmd, timeout=600):
    return subprocess.run([str(c) for c in cmd], capture_output=True, creationflags=NO_WINDOW, timeout=timeout,
                          stdin=subprocess.DEVNULL)


def _is_project(src):
    s = str(src).strip()
    return s.lower().endswith('.mlt') or s.lower() in ('live', 'current', 'editor') or Path(s).is_dir()


def _show(labels):
    """Which texts the pictures carry: True (default) = item titles, frame times and lane names; False = none;
    a list picks from 'title', 'time', 'lane'."""
    if labels is None or labels is True:
        return {'title', 'time', 'lane'}
    if labels is False:
        return set()
    if isinstance(labels, str):
        labels = [labels]
    return {str(x) for x in labels}


def _lane_specs(lanes, allowed, default):
    out = []
    for lane in (default if lanes is None else lanes):
        spec = {'lane': lane} if isinstance(lane, str) else dict(lane)
        spec['lane'] = spec.get('lane') or spec.get('kind') or spec.get('name')
        if spec['lane'] not in allowed:
            raise ValueError(f"unknown lane {spec['lane']!r}; lanes: {', '.join(allowed)}")
        out.append(spec)
    return out


def _save_jpeg(img, path, quality=86):
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=quality)
    Path(path).write_bytes(buf.getvalue())
    return buf.getvalue()


def _save_png(img, path):
    buf = io.BytesIO()
    img.save(buf, 'PNG', optimize=False)
    Path(path).write_bytes(buf.getvalue())
    return buf.getvalue()


# ---------------------------------------------------------------------------- frames of a file

def _grab(path, t, dest, media='video'):
    """The frame of a video at t seconds (an image file: the picture) saved full-size as a PNG at dest; dest or None."""
    from PIL import Image, ImageOps
    dest = Path(dest)
    if media == 'image':
        try:
            with Image.open(path) as im:
                ImageOps.exif_transpose(im).convert('RGB').save(dest)
            return dest
        except Exception:  # noqa: BLE001 - a format PIL can't read: ffmpeg below
            _quiet([FFMPEG, '-v', 'error', '-y', '-i', path, '-frames:v', '1', '-pix_fmt', 'rgb24', '-update', '1', dest])
            return dest if dest.exists() else None
    for at in (t, t - 0.05, t - 0.25, t - 1.0):      # a time in the last frame of a file gives no picture
        _quiet([FFMPEG, '-v', 'error', '-y', '-ss', f'{max(0.0, at):.3f}', '-i', path, '-frames:v', '1',
                '-pix_fmt', 'rgb24', '-update', '1', dest], timeout=120)
        if dest.exists() and dest.stat().st_size:
            return dest
        if at <= 0:
            break
    return None


def _box(region, w, h):
    """[x0, y0, x1, y1] as fractions of the frame (all values 0-1) or pixels -> pixel box inside a w x h frame."""
    if region is None:
        return None
    if isinstance(region, dict):
        region = [region.get('x0', region.get('x', 0)), region.get('y0', region.get('y', 0)),
                  region.get('x1', (region.get('x', 0) + region['w']) if 'w' in region else 1),
                  region.get('y1', (region.get('y', 0) + region['h']) if 'h' in region else 1)]
    x0, y0, x1, y1 = [float(v) for v in region]
    if max(x0, y0, x1, y1) <= 1.0:
        x0, x1, y0, y1 = x0 * w, x1 * w, y0 * h, y1 * h
    x0, x1 = sorted((max(0, min(w, round(x0))), max(0, min(w, round(x1)))))
    y0, y1 = sorted((max(0, min(h, round(y0))), max(0, min(h, round(y1)))))
    if x1 - x0 < 1 or y1 - y0 < 1:
        raise ValueError(f'region {region} leaves nothing of a {w}x{h} frame')
    return [x0, y0, x1, y1]


# ---------------------------------------------------------------------------- a source: file or project

class _Src:
    """A file or a project: its length, frames at times, its sound over a span, words and speech spans."""

    def __init__(self, kind, src, work):
        self.kind, self.work = kind, Path(work)
        self.work.mkdir(parents=True, exist_ok=True)
        self._sounds, self._words, self._speech, self._script = {}, {}, None, None
        self.fixed_sound = None          # (wav, start_s): a render already made (try_changes)
        self.render = None               # (video file, start_s): frames come from this render (try_changes)
        if kind == 'project':
            self.timeline, self.path = checks.resolve(src)
            self.duration = self.timeline.seconds
            self.fps = self.timeline.fps
            self.media = 'project'
            self.has_sound = True
            self.size = (self.timeline.profile['width'], self.timeline.profile['height'])
        else:
            self.path = Path(src)
            if not self.path.is_file():
                raise FileNotFoundError(f'No file at {src}')
            info = core_tools.probe(self.path)
            self.duration = float(info.get('duration') or 0)
            self.fps = float(info.get('fps') or 0) or 30.0
            self.media = core_tools._kind(self.path)
            self.has_sound = bool(info.get('audio'))
            self.size = (info.get('width') or 0, info.get('height') or 0)
            if self.media == 'image' and not all(self.size):
                try:
                    from PIL import Image
                    with Image.open(self.path) as im:
                        self.size = im.size
                except Exception:  # noqa: BLE001
                    self.size = (16, 9)
        self.name = self.path.name

    def script(self):
        if self._script is None:
            import letitedit.timeline.edit_script as es
            self._script = es.read(self.path)
        return self._script

    def frames(self, times, folder):
        """PNG path (or None) per time: export frames for a project, decoded frames for a file."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        if not times:
            return []
        if self.render is not None:
            video, start = self.render
            first = round(start * self.fps)

            def from_render(kt):
                k, t = kt
                rel = (max(first, round(t * self.fps)) - first + 0.5) / self.fps
                return _grab(video, rel, folder / f'f_{k + 1:04d}.png')
            with ThreadPoolExecutor(max_workers=4) as pool:
                return list(pool.map(from_render, enumerate(times)))
        if self.kind == 'project':
            picks = [round(t * self.fps) for t in times]
            fresh = folder / f'melt-{uuid.uuid4().hex[:6]}'          # render_frames reads back every f_*.png there
            fresh.mkdir(parents=True, exist_ok=True)
            return [Path(p) for p in checks.render_frames(self.timeline, self.path, picks, fresh)]
        if self.media == 'audio':
            return [None] * len(times)
        if self.media == 'image':
            one = _grab(self.path, 0, folder / 'f_0001.png', 'image')
            return [one] * len(times)

        def grab(kt):
            k, t = kt
            return _grab(self.path, t, folder / f'f_{k + 1:04d}.png', self.media)
        with ThreadPoolExecutor(max_workers=4) as pool:
            return list(pool.map(grab, enumerate(times)))

    def sound(self, a, b):
        """(wav path or None, the wav's start in seconds): 48 kHz stereo sound from PREROLL s before a to b."""
        if self.fixed_sound is not None:
            return self.fixed_sound
        key = (round(a, 3), round(b, 3))
        if key not in self._sounds:
            self._sounds[key] = self._make_sound(a, b)
        return self._sounds[key]

    def _make_sound(self, a, b):
        a0 = max(0.0, a - PREROLL)
        wav = self.work / f'sound_{len(self._sounds) + 1}_{uuid.uuid4().hex[:4]}.wav'
        if self.kind == 'project':
            first = max(0, round(a0 * self.fps))
            last = min(self.timeline.frames - 1, max(first, round(b * self.fps) - 1))
            checks.render_audio(self.path, wav, first, last)
            return wav, first / self.fps
        if not self.has_sound or b <= a0:
            return None, a0
        _quiet([FFMPEG, '-v', 'error', '-y', '-ss', f'{a0:.3f}', '-t', f'{b - a0:.3f}', '-i', self.path, '-vn', '-ac', '2',
                '-ar', '48000', '-c:a', 'pcm_s16le', wav])
        return (wav, a0) if wav.exists() and wav.stat().st_size > 100 else (None, a0)

    def words(self, a, b):
        """[(word, start, end)] said between a and b (timeline seconds for a project, source seconds for a file)."""
        key = (round(a, 3), round(b, 3))
        if key not in self._words:
            if self.kind == 'project':
                import letitedit.timeline.timeline_speech as timeline_speech
                got = [(w['w'].strip(), w['t0'], w['t1']) for w in timeline_speech.timeline_words(self.script(), a, b)]
            elif not self.has_sound:
                got = []
            else:
                import letitedit.footage.speech as speech
                got = [(w['w'].strip(), float(w['s']), float(w['e'])) for w in speech.words(str(self.path), a, b)]
            self._words[key] = got
        return self._words[key]

    def speech(self, a, b):
        """[[start, end]] where someone talks, inside a-b."""
        if self._speech is None:
            import letitedit.sound.music as music
            if self.kind == 'project':
                self._speech = music.speech_spans(self.script())
            elif not self.has_sound:
                self._speech = []
            else:
                self._speech = music.voice_times(str(self.path))
        return [[max(a, s), min(b, e)] for s, e in self._speech if e > a and s < b]


def _item_source(raw):
    """(item dict, 'project' | 'file', source)"""
    it = {'file': str(raw)} if isinstance(raw, (str, Path)) else dict(raw)
    if it.get('project') is not None:
        return it, 'project', str(it['project'])
    src = it.get('file') or it.get('source') or it.get('clip')
    if src is None:
        raise ValueError('every item needs a file or a project')
    return it, ('project' if _is_project(src) else 'file'), str(src)


def _pick(spec, dur, count_default=8, pad_default=1.0):
    """(times, span [a, b], how) from times, or range [a, b] with count / every_s, or the whole source."""
    last = max(0.0, dur - 0.02) if dur else 0.0

    def clamp(t):
        return min(max(0.0, float(t)), last) if dur else 0.0
    if spec.get('times') is not None:
        times = [float(t) for t in (spec['times'] if isinstance(spec['times'], (list, tuple)) else [spec['times']])]
        if not times:
            raise ValueError('times is empty')
        pad = float(spec.get('pad', pad_default))
        span = spec.get('span') or [max(0.0, min(times) - pad), (min(dur, max(times) + pad) if dur else max(times) + pad)]
        how = {'times': [_r(t) for t in times], 'pad': pad}
    else:
        rng = spec.get('range')
        a, b = (float(rng[0]), float(rng[1])) if rng else (0.0, float(dur))
        if dur:
            b = min(b, float(dur))
        if b <= a:
            raise ValueError(f'range {rng}: the end must be after the start (length {dur:.2f} s)')
        if spec.get('every_s'):
            step = float(spec['every_s'])
            if step <= 0:
                raise ValueError('every_s must be more than 0')
            n = max(1, round((b - a) / step))
            times = [a + (k + 0.5) * step for k in range(n)]
            span = [a, a + n * step]
            how = {'range': [_r(a), _r(b)], 'every_s': step, 'count': n, 'frames_at': 'the middle of each slot'}
        else:
            n = max(1, int(spec.get('count') or count_default))
            times = [a + (k + 0.5) * (b - a) / n for k in range(n)]
            span = [a, b]
            how = {'range': [_r(a), _r(b)], 'count': n, 'frames_at': 'the middle of each of count equal slots'}
    span = [float(span[0]), float(span[1])]
    if span[1] <= span[0]:
        span[1] = span[0] + 1.0
    return [clamp(t) for t in times], span, how


# ---------------------------------------------------------------------------- sound helpers

def _pcm(wav, a0, a, b, sr=16000):
    """Mono float samples covering a-b (the wav starts at a0 s); silence where the wav has nothing."""
    n = max(1, int(round((b - a) * sr)))
    out = np.zeros(n, np.float32)
    if wav is None:
        return out
    skip = max(0.0, a - a0)
    r = _quiet([FFMPEG, '-v', 'error', '-ss', f'{skip:.4f}', '-t', f'{b - max(a, a0):.4f}', '-i', wav, '-ac', '1',
                '-ar', str(sr), '-f', 'f32le', '-'])
    y = np.frombuffer(r.stdout[:len(r.stdout) // 4 * 4], np.float32)
    off = max(0, int(round((a0 - a) * sr)))
    k = max(0, min(len(y), n - off))
    out[off:off + k] = y[:k]
    return out


def _loudness(wav, a0, a, b, work):
    """(series [(t, momentary, short_term)] in source/timeline seconds, summary of a-b: integrated, range, peak)."""
    series, _ = checks.loudness_series(wav)
    series = [(a0 + t, m, s) for t, m, s in series]
    trimmed = Path(work) / f'span_{uuid.uuid4().hex[:6]}.wav'
    _quiet([FFMPEG, '-v', 'error', '-y', '-ss', f'{max(0.0, a - a0):.4f}', '-t', f'{b - max(a, a0):.4f}', '-i', wav,
            '-c:a', 'pcm_s16le', trimmed])
    summary = {}
    if trimmed.exists():
        _, summary = checks.loudness_series(trimmed)
        trimmed.unlink(missing_ok=True)
    return series, summary


def _reading(series, t, a0=None):
    """The loudness reading nearest t: (momentary, short_term) or None; a reading whose window reaches back before
    the rendered sound's start a0 (0.4 s momentary, 3 s short-term) is None."""
    if not series:
        return None
    best = min(series, key=lambda r: abs(r[0] - t))
    if abs(best[0] - t) > 0.3:
        return None
    m, s = best[1], best[2]
    if a0 is not None:
        m = m if best[0] >= a0 + 0.4 - 1e-6 else None
        s = s if best[0] >= a0 + 3.0 - 1e-6 else None
    return (m, s)


def _full(series, a0):
    """series with momentary / short-term readings set to None while their window isn't full of rendered sound."""
    return [(t, m if t >= a0 + 0.4 - 1e-6 else None, s if t >= a0 + 3.0 - 1e-6 else None) for t, m, s in series]


def _cmap(v):
    """0-1 array -> RGB uint8 (dark purple -> orange -> pale yellow)."""
    stops = np.array([0.0, 0.2, 0.45, 0.7, 0.88, 1.0])
    cols = np.array([[6, 4, 18], [50, 16, 100], [150, 40, 110], [230, 95, 60], [252, 175, 70], [252, 250, 200]], float)
    out = np.empty(v.shape + (3,), np.uint8)
    for c in range(3):
        out[..., c] = np.interp(v, stops, cols[:, c]).astype(np.uint8)
    return out


# ---------------------------------------------------------------------------- lanes under frames (look, try_changes)

def _lane(spec, src, a, b, w, marks, named=True):
    """A lane image w px wide over a-b of src, and its data."""
    from PIL import Image, ImageDraw
    kind = spec['lane']
    h = int(spec.get('height') or LANE_H[kind])
    w = max(20, int(w))
    img = Image.new('RGB', (w, h), LANE_BG)
    d = ImageDraw.Draw(img)
    small = _font(10)

    def X(t):
        return (t - a) / (b - a) * w
    info = {'lane': kind, 'height': h, 'span': [_r(a), _r(b)]}
    if kind in SOUND_LANES:
        wav, a0 = src.sound(a, b)
        if wav is None:
            d.text((w // 2 - 20, h // 2 - 6), 'no sound', fill=DIM, font=small)
            info['none'] = 'no sound'
        elif kind == 'waveform':
            sr = int(spec.get('rate', 16000))
            y = _pcm(wav, a0, a, b, sr)
            gain = 10 ** (float(spec.get('gain_db', 0)) / 20)
            edges = np.linspace(0, len(y), w + 1).astype(int)
            idx = np.minimum(edges[:-1], len(y) - 1)
            mx, mn = np.maximum.reduceat(y, idx), np.minimum.reduceat(y, idx)
            sq = np.add.reduceat(y.astype(np.float64) ** 2, idx)
            cnt = np.maximum(1, np.diff(np.append(idx, len(y))))
            rms = np.sqrt(sq / cnt)
            mid = (h - 1) / 2
            d.line((0, mid, w, mid), fill=(70, 70, 80))
            for x in range(w):
                d.line((x, mid - min(1, mx[x] * gain) * mid, x, mid - max(-1, mn[x] * gain) * mid), fill=(80, 150, 210))
                r_ = min(1, rms[x] * gain) * mid
                d.line((x, mid - r_, x, mid + r_), fill=(150, 205, 250))
            peak = float(np.abs(y).max()) if y.size else 0.0
            info.update(scale=f'full scale (0 dBFS) at the lane edges' + (f", gain {spec['gain_db']} dB" if spec.get('gain_db') else ''),
                        rate=sr, peak_dbfs=_r(20 * math.log10(max(peak, 1e-9)), 1),
                        rms_dbfs=_r(10 * math.log10(max(float(np.mean(y.astype(np.float64) ** 2)), 1e-18)), 1))
        elif kind == 'spectrogram':
            sr = int(spec.get('rate', 16000))
            y = _pcm(wav, a0, a, b, sr)
            nfft = int(spec.get('nfft', 512))
            max_hz = min(float(spec.get('max_hz', 8000)), sr / 2)
            min_hz = float(spec.get('min_hz', 50))
            floor = float(spec.get('floor_db', -70))
            freq = spec.get('freq', 'linear')
            centers = ((np.arange(w) + 0.5) * len(y) / w).astype(int)
            padded = np.pad(y, (nfft // 2, nfft // 2))
            frames = padded[centers[:, None] + np.arange(nfft)[None, :]] * np.hanning(nfft)[None, :]
            db = 20 * np.log10(np.abs(np.fft.rfft(frames, axis=1)) + 1e-10)
            top = float(db.max()) if db.size else 0.0
            v = np.clip((db - (top + floor)) / -floor, 0, 1)
            rows = np.geomspace(max(1.0, min_hz), max_hz, h) if freq == 'log' else np.linspace(0, max_hz, h)
            bins = np.clip(np.round(rows[::-1] / (sr / 2) * (nfft // 2)).astype(int), 0, nfft // 2)
            img.paste(Image.fromarray(_cmap(v[:, bins].T)), (0, 0))
            info.update(rate=sr, nfft=nfft, max_hz=max_hz, freq=freq, floor_db=floor,
                        level='dB relative to the loudest point of the span')
            if freq == 'log':
                info['min_hz'] = min_hz
        else:  # loudness
            series, summ = _loudness(wav, a0, a, b, src.work)
            lo, hi = float(spec.get('min', -60)), float(spec.get('max', 0))

            def Y(v):
                return h - 2 - (min(hi, max(lo, v)) - lo) / (hi - lo) * (h - 4)
            step = 10 if (h - 4) * 10 / (hi - lo) >= 14 else 20
            for db in range(int(math.ceil(lo / step) * step), int(hi) + 1, step):
                d.line((0, Y(db), w, Y(db)), fill=(55, 55, 64))
                d.text((w - 22, Y(db) - 11 if Y(db) > 12 else Y(db) + 1), f'{db}', fill=(110, 110, 120), font=small)
            full = _full(series, a0)
            pts_m = [(X(t), Y(m)) for t, m, s in full if a <= t <= b and m is not None]
            pts_s = [(X(t), Y(s)) for t, m, s in full if a <= t <= b and s is not None]
            if len(pts_m) > 1:
                d.line(pts_m, fill=(75, 95, 125), width=1)
            if len(pts_s) > 1:
                d.line(pts_s, fill=(110, 190, 255), width=2)
            info.update(summ)
            info.update(scale=[lo, hi], lines='short-term (3 s window, bright) and momentary (0.4 s, dim) LUFS')
            at = []
            for t in marks:
                r = _reading(series, t, a0)
                if r:
                    at.append({'t': _r(t), 'short_term': r[1], 'momentary': r[0]})
            info['at_frames'] = at
            if a < a0 + 3.0 - 1e-6:
                info['window_note'] = (f'sound starts at {_r(a0)} s: short-term readings begin at {_r(a0 + 3)} s, '
                                       f'momentary at {_r(a0 + 0.4)} s')
    elif kind == 'speech':
        spans = src.speech(a, b)
        for s, e in spans:
            d.rectangle((X(s), 3, max(X(s) + 1, X(e)), h - 4), fill=(90, 190, 120))
        info['spans'] = [[_r(s, 2), _r(e, 2)] for s, e in spans]
        info['talking_s'] = _r(sum(e - s for s, e in spans), 2)
    elif kind == 'words':
        words = src.words(a, b)
        rows = max(1, int(spec.get('rows', 2)))
        font = _font(int(spec.get('font', 12)))
        top = 10 if named else 0                  # the lane name has the top line to itself
        if 'height' not in spec:
            h_need = top + rows * (font.size + 2) + 6
            if h_need > h:
                h = h_need
                img = Image.new('RGB', (w, h), LANE_BG)
                d = ImageDraw.Draw(img)
                info['height'] = h
        row_h = (h - 6 - top) / rows
        ends = [-1e9] * rows
        shown = 0
        for word, t0, t1 in words:
            x0, x1 = X(t0), X(t1)
            d.line((x0, h - 3, max(x0 + 1, x1), h - 3), fill=(130, 175, 130), width=2)
            for r in range(rows):
                if x0 >= ends[r] + 3:
                    d.text((x0, top + r * row_h), word, fill=TEXT, font=font)
                    ends[r] = x0 + _tw(font, word)
                    shown += 1
                    break
        info['words'] = [[wd, _r(t0), _r(t1)] for wd, t0, t1 in words]
        info['labelled'] = shown
    for t in marks:
        x = X(t)
        d.polygon([(x - 3, 0), (x + 3, 0), (x, 4)], fill=ACCENT)
    if named:
        d.text((3, 1), kind, fill=(170, 170, 180), font=small)
    return img, info


# ---------------------------------------------------------------------------- sheets

def _tile(png, size, aspect, text):
    from PIL import Image, ImageDraw
    if png and Path(png).exists():
        im = Image.open(png).convert('RGB')
        tw = max(1, round(im.width * size / im.height))
        im = im.resize((tw, size), Image.LANCZOS)
    else:
        tw = max(1, round(size * (aspect or 16 / 9)))
        im = Image.new('RGB', (tw, size), (52, 52, 58))
        ImageDraw.Draw(im).text((6, size // 2 - 6), _fit('no picture', _font(11), tw - 8), fill=DIM, font=_font(11))
    if text:
        d = ImageDraw.Draw(im)
        f = _font(12, True)
        t = _fit(text, f, tw - 6)
        d.rectangle((0, 0, _tw(f, t) + 6, 16), fill=(0, 0, 0))
        d.text((3, 1), t, fill=ACCENT, font=f)
    return im


def _text_strip(title, width, sub=None, color=ACCENT, h=24):
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (max(40, int(width)), h), BG)
    d = ImageDraw.Draw(img)
    f, fs = _font(14, True), _font(12)
    t = _fit(title, f, img.width - 8)
    d.text((4, 4), t, fill=color, font=f)
    if sub:
        x = 4 + _tw(f, t) + 12
        d.text((x, 6), _fit(sub, fs, img.width - x - 4), fill=DIM, font=fs)
    return img


def _row(ims):
    from PIL import Image
    w = sum(im.width for im in ims) + GAP * (len(ims) - 1)
    out = Image.new('RGB', (w, max(im.height for im in ims)), BG)
    x = 0
    for im in ims:
        out.paste(im, (x, 0))
        x += im.width + GAP
    return out


def _paginate(strips, page_h, gap=3):
    """strips: [(image, keep_with_next)] stacked into pages at most page_h tall (a taller strip gets a page of its own)."""
    from PIL import Image
    pages, cur, used, i = [], [], 0, 0
    while i < len(strips):
        j = i
        while strips[j][1] and j + 1 < len(strips):
            j += 1
        group = strips[i:j + 1]
        gh = sum(s.height + gap for s, _ in group)
        if cur and used + gh > page_h:
            pages.append(cur)
            cur, used = [], 0
        cur.extend(group)
        used += gh
        i = j + 1
    if cur:
        pages.append(cur)
    out = []
    for group in pages:
        W = max(s.width for s, _ in group)
        H = sum(s.height + gap for s, _ in group)
        page = Image.new('RGB', (W, H), BG)
        y = 0
        for s, _ in group:
            page.paste(s, (0, y))
            y += s.height + gap
        out.append(page)
    return out


def _compose(blocks, layout, size, per_row, page_w, page_h, show):
    """blocks: [{'title', 'sub', 'tiles': [(png, time text, aspect)], 'lanes': [fn(width) -> image], 'note'}].
    Returns ([page images], per_row used for each block)."""
    from PIL import Image, ImageDraw
    for b in blocks:
        b['ims'] = [_tile(p, size, asp, (txt if 'time' in show else None)) for p, txt, asp in b['tiles']]
    strips, used = [], []
    lane_only_w = min(page_w, 1600)
    if layout == 'rows':
        for b in blocks:
            ims = b['ims']
            if ims:
                tw = max(im.width for im in ims)
                pr = int(per_row) if per_row else max(1, (page_w + GAP) // (tw + GAP))
                pr = max(1, min(pr, len(ims)))
                lines = [ims[k:k + pr] for k in range(0, len(ims), pr)]
                bw = max(sum(im.width for im in ln) + GAP * (len(ln) - 1) for ln in lines)
            else:
                pr, lines, bw = 0, [], lane_only_w
            used.append(pr)
            if 'title' in show:
                strips.append((_text_strip(b['title'], bw, b.get('sub')), True))
            if b.get('note'):
                strips.append((_text_strip(b['note'], max(bw, 600), color=(255, 120, 110)), bool(lines)))
            for ln in lines:
                strips.append((_row(ln), False))
            for fn in b['lanes']:
                strips.append((fn(bw), False))
            strips.append((Image.new('RGB', (10, 6), BG), False))
    elif layout == 'columns':
        cols = []
        for b in blocks:
            ims = b['ims']
            pr = max(1, min(int(per_row or 1), len(ims))) if ims else 0
            lines = [ims[k:k + pr] for k in range(0, len(ims), pr)] if ims else []
            cw = max([sum(im.width for im in ln) + GAP * (len(ln) - 1) for ln in lines] or [320])
            cols.append((lines, cw))
            used.append(pr)
        xs, x = [], 0
        for _, cw in cols:
            xs.append(x)
            x += cw + 12
        total_w = max(40, x - 12)
        if 'title' in show:
            head = Image.new('RGB', (total_w, 40), BG)
            d = ImageDraw.Draw(head)
            for b, (lines, cw), x0 in zip(blocks, cols, xs):
                d.text((x0 + 2, 3), _fit(b['title'], _font(13, True), cw - 4), fill=ACCENT, font=_font(13, True))
                if b.get('sub'):
                    d.text((x0 + 2, 21), _fit(b['sub'], _font(11), cw - 4), fill=DIM, font=_font(11))
            strips.append((head, True))
        notes = [(b.get('note'), x0, cw) for b, (_, cw), x0 in zip(blocks, cols, xs) if b.get('note')]
        if notes:
            nimg = Image.new('RGB', (total_w, 20), BG)
            d = ImageDraw.Draw(nimg)
            for note, x0, cw in notes:
                d.text((x0 + 2, 3), _fit(note, _font(11), cw - 4), fill=(255, 120, 110), font=_font(11))
            strips.append((nimg, True))
        for k in range(max([len(ln) for ln, _ in cols] or [0])):
            parts = [(cols[i][0][k], xs[i]) for i in range(len(cols)) if k < len(cols[i][0])]
            row = Image.new('RGB', (total_w, max(_row(ln).height for ln, _ in parts)), BG)
            for ln, x0 in parts:
                row.paste(_row(ln), (x0, 0))
            strips.append((row, False))
        for j in range(max([len(b['lanes']) for b in blocks] or [0])):
            imgs = [(b['lanes'][j](cw), x0) for b, (_, cw), x0 in zip(blocks, cols, xs) if j < len(b['lanes'])]
            row = Image.new('RGB', (total_w, max(im.height for im, _ in imgs)), BG)
            for im, x0 in imgs:
                row.paste(im, (x0, 0))
            strips.append((row, False))
    else:  # grid
        flat = []
        for n, b in enumerate(blocks, 1):
            for (p, txt, asp) in b['tiles']:
                label = f"{n} · {txt}" if 'time' in show else (str(n) if 'title' in show else None)
                flat.append(_tile(p, size, asp, label))
        if flat:
            tw = max(im.width for im in flat)
            pr = int(per_row) if per_row else max(1, (page_w + GAP) // (tw + GAP))
            pr = max(1, min(pr, len(flat)))
            lines = [flat[k:k + pr] for k in range(0, len(flat), pr)]
            gw = max(sum(im.width for im in ln) + GAP * (len(ln) - 1) for ln in lines)
            if 'title' in show:
                key = '   '.join(f"{n} = {b['title'].split('. ', 1)[-1]}" for n, b in enumerate(blocks, 1))
                strips.append((_text_strip(key, gw), True))
            for ln in lines:
                strips.append((_row(ln), False))
        else:
            pr, gw = 0, lane_only_w
        used = [pr] * len(blocks)
        for b in blocks:
            if b['lanes'] or b.get('note'):
                if 'title' in show:
                    strips.append((_text_strip(b['title'], gw, b.get('sub')), True))
                if b.get('note'):
                    strips.append((_text_strip(b['note'], gw, color=(255, 120, 110)), bool(b['lanes'])))
                for fn in b['lanes']:
                    strips.append((fn(gw), False))
    if not strips:
        strips = [(_text_strip('(nothing to show)', 400), False)]
    return _paginate(strips, page_h), used


def _defaults(**given):
    """{name: value} of the parameters left at their default (value None in `given` maps to the default used)."""
    return {k: v[1] for k, v in given.items() if v[0] is None}


# ---------------------------------------------------------------------------- look

def look(items, layout=None, size=None, per_row=None, labels=None, lanes=None, out_dir=None, page_w=None,
         page_h=None):
    """A comparison sheet of frames from files and projects.

    items: list of {file | project, times | range (+ count | every_s) | (nothing: the whole source), crop, label,
    lanes, pad, span}. `file` is any video, image or sound file (source seconds); `project` an .mlt rendered by melt
    (timeline seconds). times: seconds; range [a, b] split into `count` equal slots (default 8) or slots of `every_s`
    seconds, a frame at the middle of each; crop [x0, y0, x1, y1] (0-1 fractions of the frame, each frame); lanes per
    item override `lanes`; pad (s, default 1) widens the lane span around `times`, span [a, b] sets it.
    layout: 'rows' (one row per item; default), 'columns' (one column per item) or 'grid' (all frames in one grid).
    size: frame height px (default 240). per_row: frames per line (default: as many as fit page_w; 'columns': 1).
    labels: True (titles, frame times, lane names; default), False, or a list from 'title', 'time', 'lane'.
    lanes: under each item's frames over its span: 'waveform', 'spectrogram', 'loudness' (short-term LUFS),
    'speech' (voice spans), 'words', or dicts {lane, height, ...} (waveform: gain_db; spectrogram: max_hz, min_hz,
    freq 'linear' | 'log', nfft, floor_db; loudness: min, max; words: rows, font).
    page_w / page_h: page size px (default 2400 / 2400).
    Returns ([jpeg bytes per page], info): every frame's time, source and PNG path, lane data, sheet paths."""
    started = time.monotonic()
    if not items:
        raise ValueError('items is empty')
    defaults = _defaults(layout=(layout, 'rows'), size=(size, 240), per_row=(per_row, 'fit page_w'),
                         labels=(labels, True), lanes=(lanes, []), page_w=(page_w, 2400), page_h=(page_h, 2400))
    layout = layout or 'rows'
    if layout not in ('rows', 'columns', 'grid'):
        raise ValueError("layout: 'rows', 'columns' or 'grid'")
    size = int(size or 240)
    page_w, page_h = int(page_w or 2400), int(page_h or 2400)
    show = _show(labels)
    work = _folder(out_dir, 'look')
    lane_default = _lane_specs(lanes, LOOK_LANES, [])

    def prep(n_raw):
        n, raw = n_raw
        it, kind, src = _item_source(raw)
        s = _Src(kind, src, work / f'item{n}')
        specs = _lane_specs(it['lanes'], LOOK_LANES, []) if it.get('lanes') is not None else lane_default
        if s.media == 'image':
            times, span, how = [0.0], [0.0, 1.0], {'picture': True}
            specs = []
        elif s.media == 'audio':
            _, span, how = _pick(it, s.duration, 8)
            how = {'range': how.get('range') or [_r(span[0]), _r(span[1])], 'sound only': True}
            times = []
        else:
            times, span, how = _pick(it, s.duration, 8)
        pngs = s.frames(times, work / f'item{n}')
        crop = it.get('crop')
        frames = []
        for t, p in zip(times, pngs):
            f = {'item': n, 'time': _r(t), 'clock': _clock(t)}
            if p is not None and crop:
                from PIL import Image
                with Image.open(p) as im:
                    box = _box(crop, im.width, im.height)
                    cp = Path(p).with_name(Path(p).stem + '_crop.png')
                    im.convert('RGB').crop(box).save(cp)
                f.update(png=str(cp), full=str(p), crop_px=box)
            elif p is not None:
                f['png'] = str(p)
            else:
                f['png'] = None
            frames.append(f)
        if any(sp['lane'] in SOUND_LANES for sp in specs):
            s.sound(*span)
        if any(sp['lane'] == 'words' for sp in specs):
            s.words(*span)
        return n, it, s, times, span, how, frames, specs

    with ThreadPoolExecutor(max_workers=min(3, len(items))) as pool:
        prepared = list(pool.map(prep, enumerate(items, 1)))

    blocks, out_items = [], []
    for n, it, s, times, span, how, frames, specs in prepared:
        label = str(it.get('label') or s.name)
        w, h = s.size if all(s.size) else (16, 9)
        crop = it.get('crop')
        if crop and frames and frames[0].get('crop_px'):
            x0, y0, x1, y1 = frames[0]['crop_px']
            w, h = x1 - x0, y1 - y0
        entry = {'n': n, 'label': label, 'source': str(s.path), 'kind': s.media, 'length': _r(s.duration), **how,
                 'span': [_r(span[0]), _r(span[1])], 'frames': frames, 'lanes': {}}
        if crop:
            entry['crop'] = crop
        lane_fns = []
        for spec in specs:
            def fn(width, spec=spec, s=s, span=span, times=times, entry=entry):
                img, data = _lane(spec, s, span[0], span[1], width, times, 'lane' in show)
                entry['lanes'][spec['lane']] = data
                return img
            lane_fns.append(fn)
        sub = f"{s.name}  {_clock(span[0])}-{_clock(span[1])}" if s.media != 'image' else s.name
        blocks.append({'title': f'{n}. {label}', 'sub': sub, 'lanes': lane_fns,
                       'tiles': [(f['png'], f['clock'] if s.media != 'image' else None, w / h) for f in frames]})
        out_items.append(entry)
    pages, per_rows = _compose(blocks, layout, size, per_row, page_w, page_h, show)
    images, sheets = [], []
    for i, page in enumerate(pages, 1):
        p = work / f'look_{i}.jpg'
        images.append(_save_jpeg(page, p))
        sheets.append(str(p))
    for entry, pr in zip(out_items, per_rows):
        entry['per_row'] = pr
    info = {'layout': layout, 'size': size, 'per_row': per_row or per_rows, 'labels': sorted(show),
            'lanes': [sp['lane'] for sp in lane_default], 'page_w': page_w, 'page_h': page_h, 'items': out_items,
            'sheets': sheets, 'folder': str(work), 'defaults': defaults,
            'rendered_by': 'melt (export engine) for projects, ffmpeg for files',
            'seconds': round(time.monotonic() - started, 1)}
    return images, info


# ---------------------------------------------------------------------------- try_changes: reuse of renders

_REUSE_LOCK = threading.Lock()
_REUSE = {}            # a scratch copy's graphics/made folder -> folders holding the original project's renders
_REAL = {}
_ACTIVE = [0]


def _key(path):
    return os.path.normcase(os.path.abspath(str(path)))


def _graphic_hit(recipe, width, height, fps, kit, folders):
    """The original project's file for this graphic recipe, as graphics.render would return it, or None."""
    import letitedit.pictures.graphics as graphics
    import letitedit.looks.style_pack as style_pack
    import letitedit.looks.look_library as look_library
    kit_ = kit if isinstance(kit, style_pack.Kit) else look_library.kit(kit)
    rec = graphics.normalise(recipe, kit_)
    mod = graphics._resolve_template(rec, kit_)
    animated = getattr(mod, 'ANIMATED', True) if mod else bool(rec['params'].get('animated', True))
    name = f"{rec['template']}-{graphics._digest(rec, kit_, width, height, fps)}"
    opaque = bool(rec.get('source')) and not rec['params'].get('alpha')
    fname = name + (('.mp4' if opaque else '.mov') if animated else '.png')
    for d in folders:
        p = Path(d) / fname
        if p.exists():
            n = max(1, int(round(rec['len'] * fps))) if animated else 1
            return {'path': str(p), 'recipe': rec, 'animated': animated, 'frames': n, 'cached': True}
    return None


def _made_hit(recipe, width, height, fps, folders):
    """The original project's file for this made-clip recipe, as made.render would return it, or None."""
    import letitedit.timeline.made as made
    kind = recipe.get('kind')
    if kind == 'fx':
        files = dict(recipe, inputs=[i for st in recipe['stages'] for i in st.get('inputs', [])])
        fname, alpha = f"fx-{made._digest(files, width, height, fps)}{'.mp4' if recipe.get('picture', True) else '.wav'}", False
    elif kind == 'ass':
        fname, alpha = f'ass-{made._digest(recipe, width, height, fps)}.mov', True
    elif kind in ('vfx', 'voice') or not kind:
        return None
    else:
        alpha = bool(recipe.get('alpha'))
        ext = '.png' if kind in ('freeze', 'still') else ('.mov' if alpha else '.mp4')
        fname = f'{kind}-{made._digest(recipe, width, height, fps)}{ext}'
    for d in folders:
        p = Path(d) / fname
        if p.exists():
            return {'path': str(p), 'cached': True, 'alpha': alpha}
    return None


def _graphics_render(recipe, width=1920, height=1080, fps=30.0, kit=None, out_dir=None):
    folders = _REUSE.get(_key(out_dir)) if out_dir else None
    if folders:
        try:
            hit = _graphic_hit(recipe, width, height, fps, kit, folders)
        except Exception:  # noqa: BLE001 - no reuse: render as usual
            hit = None
        if hit:
            return hit
    return _REAL['graphics'](recipe, width, height, fps, kit=kit, out_dir=out_dir)


def _made_render(recipe, width=1920, height=1080, fps=30.0, out_dir=None):
    folders = _REUSE.get(_key(out_dir)) if out_dir else None
    if folders:
        try:
            hit = _made_hit(recipe, width, height, fps, folders)
        except Exception:  # noqa: BLE001 - no reuse: render as usual
            hit = None
        if hit:
            return hit
    return _REAL['made'](recipe, width, height, fps, out_dir=out_dir)


@contextlib.contextmanager
def _reusing(folders):
    """While active, graphics and made clips that a scratch copy needs and the original project already has are
    taken from the original's folders (read only) instead of being rendered again; new ones go to the copy's folders."""
    import letitedit.pictures.graphics as graphics
    import letitedit.timeline.made as made
    keys = []
    with _REUSE_LOCK:
        if _ACTIVE[0] == 0:
            _REAL['graphics'], _REAL['made'] = graphics.render, made.render
            graphics.render, made.render = _graphics_render, _made_render
        _ACTIVE[0] += 1

    def add(vdir):
        with _REUSE_LOCK:
            for sub in ('graphics', 'made'):
                k = _key(Path(vdir) / sub)
                _REUSE[k] = list(folders)
                keys.append(k)
    try:
        yield add
    finally:
        with _REUSE_LOCK:
            for k in keys:
                _REUSE.pop(k, None)
            _ACTIVE[0] -= 1
            if _ACTIVE[0] == 0:
                graphics.render, made.render = _REAL['graphics'], _REAL['made']


def _render_folders(project):
    """Folders of the renders a project uses: its graphics/ and made/ folders and those its clips point into."""
    p = Path(project)
    out = [p.parent / 'graphics', p.parent / 'made']
    text = p.read_text(encoding='utf-8', errors='replace')
    for m in re.finditer(r'<property name="(?:resource|warp_resource)">([^<]+)</property>', text):
        res = Path(m.group(1).replace('&amp;', '&'))
        if res.is_absolute() and res.parent.name.lower() in ('graphics', 'made') and res.parent not in out:
            out.append(res.parent)
    return [d for d in out if d.is_dir()]


# ---------------------------------------------------------------------------- try_changes

def _norm(word):
    return re.sub(r'[^\w]', '', str(word).lower())


def _find_phrase(words, phrase):
    """[(start, end, clip id)] of every place the phrase is said, from timeline words."""
    want = [x for x in (_norm(p) for p in str(phrase).split()) if x]
    ws = [(w, _norm(w['w'])) for w in words]
    ws = [(w, n) for w, n in ws if n]
    out = []
    for i in range(len(ws) - len(want) + 1):
        if all(ws[i + k][1] == want[k] for k in range(len(want))):
            out.append((ws[i][0]['t0'], ws[i + len(want) - 1][0]['t1'], ws[i][0].get('id')))
    return out


def _align(align, src, frames):
    """(times, span, how) for one version, or (None, None, how) when the alignment isn't on this version."""
    from letitedit.timeline.edit_sync import layout
    L = src.duration
    if not align:
        n = int(frames or 8)
        times, span, how = _pick({'count': n}, L, n)
        how = {'spread': 'whole timeline', 'count': n}
        return times, span, how
    align = dict(align)
    count = align.get('count') or frames or 6
    if 'at' in align:
        times, span, how = _pick({'times': align['at'], 'pad': align.get('pad', 1.0)}, L)
        return times, span, how
    if 'range' in align:
        return _pick({'range': align['range'], 'count': count, 'every_s': align.get('every_s')}, L, int(count))
    if 'words' in align:
        import letitedit.timeline.timeline_speech as timeline_speech
        found = _find_phrase(timeline_speech.timeline_words(src.script()), align['words'])
        how = {'words': align['words'], 'found': [[_r(a), _r(b), cid] for a, b, cid in found]}
        if not found:
            return None, None, how
        k = max(1, int(align.get('occurrence', 1)))
        a, b, _ = found[min(k, len(found)) - 1]
        pad = float(align.get('pad', 0.5))
        times, span, h2 = _pick({'range': [max(0.0, a - pad), min(L, b + pad)], 'count': count,
                                 'every_s': align.get('every_s')}, L, int(count))
        how.update(h2, occurrence=min(k, len(found)), pad=pad)
        return times, span, how
    if 'id' in align:
        hit = None
        for t in src.script()['tracks']:
            for it, s, e in layout(t):
                if it.get('id') == align['id']:
                    hit = (s, e, t['name'])
                    break
            if hit:
                break
        how = {'id': align['id']}
        if not hit:
            return None, None, how
        pad = float(align.get('pad', 0.0))
        times, span, h2 = _pick({'range': [max(0.0, hit[0] - pad), min(L, hit[1] + pad)], 'count': count,
                                 'every_s': align.get('every_s')}, L, int(count))
        how.update(h2, clip=[_r(hit[0]), _r(hit[1])], track=hit[2], pad=pad)
        return times, span, how
    raise ValueError("align: {'at': [s...]}, {'words': 'phrase'}, {'id': clip id} or {'range': [a, b]}")


def _render_span(src, a0, b, out, width, height_min):
    """melt render of a-b of a project (picture width px, PCM sound). Returns (start_s, end_s, W, H)."""
    tl = src.timeline
    p = tl.profile
    W = max(64, int(width)) // 2 * 2
    H = round(p['height'] * W / p['width'] / 2) * 2
    if H < height_min:
        H = int(height_min + 1) // 2 * 2
        W = round(p['width'] * H / p['height'] / 2) * 2
    first = max(0, round(a0 * tl.fps))
    last = min(tl.frames - 1, max(first, round(b * tl.fps) - 1))
    checks._run([MELT, '-quiet', src.path, f'in={first}', f'out={last}', '-consumer', f'avformat:{out}',
                 'vcodec=libx264', 'crf=20', 'preset=veryfast', 'pix_fmt=yuv420p', 'acodec=pcm_s16le', 'ar=48000',
                 'channels=2', f'width={W}', f'height={H}', f'progressive={p["progressive"]}',
                 f'frame_rate_num={p["frame_rate_num"]}', f'frame_rate_den={p["frame_rate_den"]}',
                 'sample_aspect_num=1', 'sample_aspect_den=1', f'display_aspect_num={W}', f'display_aspect_den={H}',
                 'real_time=-1'], timeout=3600)
    return first / tl.fps, (last + 1) / tl.fps, W, H


def _card_png(label, sub, W, H, path):
    from PIL import Image, ImageDraw
    im = Image.new('RGB', (W, H), (14, 14, 18))
    d = ImageDraw.Draw(im)
    f, fs = _font(max(16, H // 8), True), _font(max(11, H // 22))
    t = _fit(label, f, W - 20)
    d.text(((W - _tw(f, t)) / 2, H / 2 - f.size), t, fill=ACCENT, font=f)
    s = _fit(sub, fs, W - 20)
    d.text(((W - _tw(fs, s)) / 2, H / 2 + 6), s, fill=(200, 200, 205), font=fs)
    im.save(path)
    return path


def _tag_png(label, W, path):
    from PIL import Image, ImageDraw
    f = _font(max(12, W // 34), True)
    t = _fit(label, f, W * 0.8)
    im = Image.new('RGBA', (int(_tw(f, t)) + 16, f.size + 12), (0, 0, 0, 170))
    ImageDraw.Draw(im).text((8, 5), t, fill=(255, 220, 0, 255), font=f)
    im.save(path)
    return path


def _review_mp4(parts, out, fps_text, W, H, card_s, burn):
    """One MP4: per part an optional title card, then its span (with its label burned in)."""
    cmd = [FFMPEG, '-v', 'error', '-y']
    filters, joins, idx = [], [], 0
    for k, p in enumerate(parts):
        if card_s > 0:
            cmd += ['-loop', '1', '-framerate', fps_text, '-t', f'{card_s:.3f}', '-i', p['card'],
                    '-f', 'lavfi', '-t', f'{card_s:.3f}', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000']
            filters.append(f'[{idx}:v]scale={W}:{H},setsar=1,fps={fps_text},format=yuv420p[cv{k}]')
            filters.append(f'[{idx + 1}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[ca{k}]')
            joins.append(f'[cv{k}][ca{k}]')
            idx += 2
        cmd += ['-ss', f"{p['skip']:.4f}", '-t', f"{p['dur']:.4f}", '-i', p['file']]
        si = idx
        idx += 1
        if burn:
            cmd += ['-i', p['tag']]
            filters.append(f'[{si}:v][{idx}:v]overlay=12:12,setsar=1,fps={fps_text},format=yuv420p[sv{k}]')
            idx += 1
        else:
            filters.append(f'[{si}:v]setsar=1,fps={fps_text},format=yuv420p[sv{k}]')
        filters.append(f'[{si}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[sa{k}]')
        joins.append(f'[sv{k}][sa{k}]')
    filters.append(''.join(joins) + f'concat=n={len(joins)}:v=1:a=1[v][a]')
    cmd += ['-filter_complex', ';'.join(filters), '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-crf', '26',
            '-preset', 'veryfast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', out]
    r = _quiet(cmd, timeout=1800)
    if r.returncode != 0 or not Path(out).exists():
        raise RuntimeError(f'ffmpeg could not join the review MP4: {r.stderr.decode(errors="replace")[-1200:]}')
    return out


def _try_versions(versions, work, original, name=None, folders_of=None):
    """Every version on its own scratch copy of the project (original: the file read, an open window's snapshot or
    the saved file; name: the copies' file name, the project's own), with its changes or code applied (an error stays
    on its row). folders_of: the saved project, whose graphics and made folders are reused too."""
    rows = []
    folders = _render_folders(original)
    if folders_of and Path(folders_of) != Path(original):
        folders += [d for d in _render_folders(folders_of) if d not in folders]
    with _reusing(folders) as add:
        for k, v in enumerate(versions, 1):
            v = dict(v) if isinstance(v, dict) else {'changes': list(v)}
            label = str(v.get('label') or f'version {k}')
            vdir = work / f'v{k}-{_slug(label)}'
            vdir.mkdir(parents=True, exist_ok=True)
            scratch = vdir / (name or original.name)
            shutil.copy2(original, scratch)
            add(vdir)
            row = {'n': k, 'label': label, 'project': str(scratch)}
            if v.get('changes') is not None:
                row['changes'] = v['changes']
            if v.get('code'):
                row['code'] = v['code']
            t0 = time.monotonic()
            try:
                if v.get('changes') or v.get('code'):
                    import letitedit_ai
                    res = letitedit_ai.apply(scratch, v.get('changes'), label=f'try: {label}', code=v.get('code'))
                    row['applied'] = {kk: res[kk] for kk in ('changes', 'notes', 'printed') if res.get(kk)}
                else:
                    row['applied'] = {'changes': [], 'notes': ['no changes: the project as it is']}
            except Exception as exc:  # noqa: BLE001 - the other versions still go ahead
                row['error'] = f'{type(exc).__name__}: {exc}'
            row['apply_seconds'] = round(time.monotonic() - t0, 1)
            rows.append(row)
    return rows


def _try_prepare(row, align, frames, opts, size):
    """One version's span rendered: its length, aligned span, frames, words and loudness (an error stays on
    its row)."""
    if row.get('error'):
        return
    vdir = Path(row['project']).parent
    src = _Src('project', row['project'], vdir)
    row['length'], row['length_s'] = _clock(src.duration), _r(src.duration)
    try:
        times, span, how = _align(align, src, frames)
    except Exception as exc:  # noqa: BLE001
        row['error'] = f'align: {type(exc).__name__}: {exc}'
        return
    row['align'] = how
    if times is None:
        row['error'] = f'not found on this version: {json.dumps({kk: how[kk] for kk in how if kk != "found"})}'
        return
    a, b = span
    a0 = max(0.0, a - PREROLL)
    seg = vdir / 'span.mkv'
    start, end, W, H = _render_span(src, a0, b, seg, opts['width'], size)
    wav = vdir / 'span.wav'
    _quiet([FFMPEG, '-v', 'error', '-y', '-i', seg, '-vn', '-c:a', 'pcm_s16le', wav])
    src.render = (seg, start)
    src.fixed_sound = (wav if wav.exists() else None, start)
    pngs = src.frames(times, vdir / 'frames')
    row['span'] = [_r(a), _r(b)]
    row['frames'] = [{'time': _r(t), 'clock': _clock(t), 'png': str(p) if p else None} for t, p in zip(times, pngs)]
    ws = src.words(a, b)
    row['words'] = {'text': ' '.join(w for w, _, _ in ws), 'words': [[w, _r(x), _r(y)] for w, x, y in ws]}
    loud = {'span': [_r(a), _r(b)]}
    if src.fixed_sound[0] is not None:
        series, summ = _loudness(wav, start, a, b, vdir)
        loud.update(summ)
        loud['at'] = [{'t': _r(t), 'short_term': r[1], 'momentary': r[0]} for t in times
                      for r in [_reading(series, t, start)] if r]
    row['loudness'] = loud
    row['_src'], row['_times'], row['_span'] = src, times, (a, b)
    row['_seg'] = {'file': str(seg), 'skip': a - start, 'dur': b - a, 'W': W, 'H': H}


def _try_blocks(rows, specs):
    """One sheet block per version: its title, its frames and a drawing function for each lane under them."""
    blocks = []
    for row in rows:
        lane_fns = []
        if row.get('_src') is not None:
            for spec in specs:
                def fn(width, spec=spec, row=row):
                    a, b = row['_span']
                    img, data = _lane(spec, row['_src'], a, b, width, row['_times'], True)
                    row.setdefault('lanes', {})[spec['lane']] = data
                    return img
                lane_fns.append(fn)
        sub = (f"length {row['length']}   span {_clock(row['_span'][0])}-{_clock(row['_span'][1])}"
               if row.get('_span') else row.get('length', ''))
        blocks.append({'title': f"{row['n']}. {row['label']}", 'sub': sub, 'note': row.get('error'),
                       'tiles': [(f['png'], f['clock'], None) for f in row.get('frames', [])], 'lanes': lane_fns})
    return blocks


def _try_mp4(rows, opts, work):
    """The MP4 of every rendered version one after another, each after an optional title card."""
    mp4, parts_info = None, []
    ok = [r for r in rows if r.get('_seg')]
    if opts.get('mp4') and ok:
        tl = ok[0]['_src'].timeline
        fps_text = f"{tl.profile['frame_rate_num']}/{tl.profile['frame_rate_den']}"
        W, H = ok[0]['_seg']['W'], ok[0]['_seg']['H']
        card_s = float(opts.get('card_s') or 0)
        parts, at = [], 0.0
        for r in ok:
            vdir = Path(r['project']).parent
            seg = dict(r['_seg'])
            seg['card'] = str(_card_png(r['label'], f"{_clock(r['_span'][0])}-{_clock(r['_span'][1])} of {r['length']}",
                                        W, H, vdir / 'card.png'))
            seg['tag'] = str(_tag_png(r['label'], W, vdir / 'tag.png'))
            parts.append(seg)
            parts_info.append({'label': r['label'], 'card_at': _r(at) if card_s else None,
                               'starts_at': _r(at + card_s), 'duration': _r(seg['dur']),
                               'shows': [_r(r['_span'][0]), _r(r['_span'][1])]})
            at += card_s + seg['dur']
        mp4 = work / 'versions.mp4'
        _review_mp4(parts, mp4, fps_text, W, H, card_s, bool(opts.get('label', True)))
    return mp4, parts_info


def try_changes(project, versions, align=None, size=None, frames=None, render=True, lanes=None, out_dir=None,
                per_row=None, page_w=None, page_h=None):
    """Versions of an edit side by side. Versions start from the project as it is now (an open window's unsaved
    state included). Each version has its own scratch copy; the project file itself is never written.

    versions: list of {label, changes (edit ops) | code (Python, as in letitedit_ai.apply)}; one with neither is the
    project as it is. align: how the versions line up: {'at': [timeline s], pad} | {'words': 'phrase', occurrence,
    pad (0.5)} (where it is said on each version) | {'id': clip id, pad (0)} (that clip's span on each version) |
    {'range': [a, b]} with count or every_s on any of them; default: frames spread over each whole timeline.
    size: frame height px (default 180). frames: frames per version (default 8 over the whole timeline, 6 over an
    aligned span; align count / every_s win). render: True / False / {'mp4': bool, 'width': px (640), 'card_s': s
    (1.0; 0 = no title cards), 'label': bool (burned label, True)}; every version's span is rendered by melt at that
    width (frames, sound and the MP4 come from it). lanes: under each row (default ['loudness', 'words']; same
    lanes as look). per_row, page_w, page_h: as in look.
    Returns ([jpeg bytes per page], info): per version its scratch project, the changes/code that made it, the
    change list, its length, aligned span and frame times + PNGs, words in the span, loudness (integrated over the
    span, short-term and momentary at each aligned time); the sheet paths and the MP4 with where each version starts."""
    started = time.monotonic()
    if not versions:
        raise ValueError('versions is empty')
    _, original = checks.resolve(project)     # an open window's state now, unsaved changes included (T298)
    original = Path(original)
    where = checks.reported(original)
    saved = Path(where['project'])
    before = _sha(saved)
    opts = {'mp4': True, 'width': 640, 'card_s': 1.0, 'label': True}
    if isinstance(render, dict):
        opts.update(render)
    elif render is False:
        opts['mp4'] = False
    defaults = _defaults(align=(align, 'frames spread over each whole timeline'), size=(size, 180),
                         frames=(frames, 'align count, else 8 (whole timeline) / 6 (span)'),
                         lanes=(lanes, TRY_LANES_DEFAULT), per_row=(per_row, 'fit page_w'),
                         page_w=(page_w, 2400), page_h=(page_h, 2400))
    if not isinstance(render, dict):
        defaults['render'] = dict(opts)
    size = int(size or 180)
    page_w, page_h = int(page_w or 2400), int(page_h or 2400)
    specs = _lane_specs(lanes, LOOK_LANES, TRY_LANES_DEFAULT)
    work = _folder(out_dir, 'try')
    rows = _try_versions(versions, work, original, name=saved.name, folders_of=saved)

    def prepare(row):
        return _try_prepare(row, align, frames, opts, size)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(prepare, rows))

    blocks = _try_blocks(rows, specs)
    show = {'title', 'time', 'lane'}
    pages, per_rows = _compose(blocks, 'rows', size, per_row, page_w, page_h, show)
    images, sheets = [], []
    for i, page in enumerate(pages, 1):
        p = work / f'try_{i}.jpg'
        images.append(_save_jpeg(page, p))
        sheets.append(str(p))

    mp4, parts_info = _try_mp4(rows, opts, work)
    after = _sha(saved)
    for r in rows:
        for kk in [kk for kk in r if kk.startswith('_')]:
            if kk == '_seg':
                r['render'] = {'file': r['_seg']['file'], 'size': [r['_seg']['W'], r['_seg']['H']]}
            r.pop(kk)
    info = {**where, 'original_unchanged': before == after, 'versions': rows,
            'align': align or {'spread': 'whole timeline'}, 'size': size, 'lanes': [sp['lane'] for sp in specs],
            'per_row': per_row or per_rows, 'render': opts, 'sheets': sheets, 'mp4': str(mp4) if mp4 else None,
            'mp4_parts': parts_info, 'folder': str(work), 'defaults': defaults,
            'note': 'each version is its own scratch project; applying one to the real project is a separate apply',
            'seconds': round(time.monotonic() - started, 1)}
    return images, info


# ---------------------------------------------------------------------------- overview

def _item_kind(it):
    for k in ('graphic', 'color', 'ffmpeg', 'freeze', 'vfx', 'ass', 'voice', 'raw'):
        if k in it:
            if k == 'graphic' and 'caption' in str((it['graphic'] or {}).get('template', '')):
                return 'caption'
            return k
    return 'clip' if 'clip' in it else 'other'


def _item_name(it):
    k = _item_kind(it)
    if k == 'clip':
        return os.path.basename(str(it['clip']))
    if k in ('graphic', 'caption'):
        g = it['graphic'] or {}
        p = g.get('params') or {}
        words = p.get('words')
        if isinstance(words, list) and words:
            return ' '.join(str(w[0]) for w in words if w)
        text = p.get('title') or p.get('text') or p.get('big') or p.get('label') or ''
        return f"{g.get('template')}: {text}" if text else str(g.get('template'))
    if k == 'color':
        return f"color {it['color']}"
    if k == 'ass':
        m = re.findall(r'Dialogue:[^,]*(?:,[^,]*){8},(.*)', str(it['ass']))
        return 'ass: ' + (re.sub(r'\{[^}]*\}', '', m[0]) if m else '')
    if k == 'vfx':
        return f"vfx: {(it['vfx'] or {}).get('effect', '')}"
    if k == 'voice':
        return f"voice: {(it['voice'] or {}).get('text', '')}"
    if k == 'ffmpeg':
        ins = (it['ffmpeg'] or {}).get('inputs') or []
        return 'ffmpeg: ' + ', '.join(os.path.basename(str(i.get('clip', ''))) for i in ins)
    if k == 'freeze':
        return f"freeze: {os.path.basename(str((it['freeze'] or {}).get('clip', '')))}"
    return k


def _pack(spans):
    """[(start, end, payload)] -> [(row, start, end, payload)] with no overlaps inside a row."""
    ends, out = [], []
    for s, e, p in sorted(spans, key=lambda x: x[0]):
        for r, last in enumerate(ends):
            if s >= last - 1e-6:
                ends[r] = e
                out.append((r, s, e, p))
                break
        else:
            ends.append(e)
            out.append((len(ends) - 1, s, e, p))
    return out, max(1, len(ends))


def _jump_text(sec):
    sign = '+' if sec >= 0 else '-'
    a = abs(sec)
    if a < 60:
        return f'{sign}{a:.1f}s'
    if a < 3600:
        return f'{sign}{int(a // 60)}m{int(a % 60):02d}s'
    if a < 86400:
        return f'{sign}{int(a // 3600)}h{int(a % 3600 // 60):02d}m'
    return f'{sign}{a / 86400:.1f}d'


class _Ov:
    """What overview's lanes draw from."""

    def __init__(self, src, a, b, work):
        from letitedit.timeline.edit_sync import layout, main_track
        self.src, self.a, self.b, self.work = src, a, b, work
        self.script = src.script()
        main = main_track(self.script)
        self.main_name = main['name'] if main else None
        self.main = [(it, s, e) for it, s, e in (layout(main) if main else []) if 'raw' not in it]
        self.tracks = [(t, [(it, s, e) for it, s, e in layout(t)]) for t in self.script['tracks']]
        self.cuts = sorted({s for _, s, _ in self.main if s > 1e-6} | {e for _, _, e in self.main})
        self._colors = {}
        for _, items in self.tracks:
            for it, _, _ in items:
                self.color(it)

    def color(self, it):
        kind = _item_kind(it)
        if kind == 'clip':
            key = os.path.normcase(str(it['clip']))
            if key not in self._colors:
                self._colors[key] = PALETTE[len(self._colors) % len(PALETTE)]
            return self._colors[key]
        if kind == 'color':
            c = str(it['color']).lstrip('#')
            try:
                if len(c) == 8:
                    c = c[2:]           # #aarrggbb
                return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                return (90, 90, 90)
        return KIND_COLOR.get(kind, (110, 110, 110))


def _block(d, X, x_lo, x_hi, s, e, y0, y1, fill, text=None, font=None, text_fill=TEXT, outline=None):
    x0, x1 = max(x_lo, X(s)), min(x_hi, X(e))
    if x1 - x0 < 0.5:
        return
    d.rectangle((x0, y0, max(x0, x1 - 1), y1), fill=fill, outline=outline)
    if text and font is not None:
        t = _fit(text, font, x1 - x0 - 4)
        if t:
            d.text((x0 + 2, y0 + 1), t, fill=text_fill, font=font)


def _ov_clips_lane(a, b, f10, f11, h, info, ov):
    def draw(img, d, y, pa, pb, X, lo, hi):
        for it, s, e in ov.main:
            if e <= pa or s >= pb:
                continue
            col = ov.color(it)
            _block(d, X, lo, hi, s, e, y + 2, y + h - 3, col, _item_name(it), f11,
                   outline=tuple(max(0, c - 50) for c in col))
            if h >= 30 and it.get('id'):
                x0 = max(lo, X(s))
                t = _fit(it['id'], f10, min(hi, X(e)) - x0 - 4)
                if t:
                    d.text((x0 + 2, y + 15), t, fill=(220, 220, 225), font=f10)
    info['clips'] = len([1 for _, s, e in ov.main if e > a and s < b])
    info['colours'] = 'one colour per source file'
    return {'height': h, 'draw': draw, 'info': info}


def _ov_tracks_lane(a, b, f10, info, ov, spec):
    row_h = int(spec.get('row_h') or spec.get('height') or LANE_H['tracks'])
    rows = ov.tracks
    H = row_h * len(rows) + 4

    def draw(img, d, y, pa, pb, X, lo, hi):
        for r, (t, items) in enumerate(rows):
            y0 = y + 2 + r * row_h
            for it, s, e in items:
                if e <= pa or s >= pb:
                    continue
                col = ov.color(it)
                if t.get('kind') == 'audio':
                    col = tuple(int(c * 0.75) for c in col)
                _block(d, X, lo, hi, s, e, y0 + 1, y0 + row_h - 2, col, _item_name(it) if row_h >= 12 else None,
                       f10)
    info['tracks'] = [{'name': t['name'], 'kind': t.get('kind'), 'items': len(items),
                       **({'hide': t['hide']} if t.get('hide') else {}),
                       'covers_s': _r(sum(max(0.0, min(e, b) - max(s, a)) for _, s, e in items))}
                      for t, items in rows]
    labels = [(t['name'] + (' (hidden)' if t.get('hide') else ''), 2 + r * row_h) for r, (t, _) in enumerate(rows)]
    return {'height': H, 'draw': draw, 'info': info, 'rows': labels, 'row_font': 10}


def _ov_speech_lane(a, b, h, info, ov):
    spans = ov.src.speech(a, b)

    def draw(img, d, y, pa, pb, X, lo, hi):
        for s, e in spans:
            if e > pa and s < pb:
                _block(d, X, lo, hi, s, e, y + 3, y + h - 4, (90, 190, 120))
    info.update(spans=[[_r(s, 2), _r(e, 2)] for s, e in spans], talking_s=_r(sum(e - s for s, e in spans), 2))
    return {'height': h, 'draw': draw, 'info': info}


def _ov_words_lane(a, b, h, info, ov, spec):
    words = ov.src.words(a, b)
    nrows = max(1, int(spec.get('rows', 2)))
    font = _font(int(spec.get('font', 11)))
    shown = [0]

    def draw(img, d, y, pa, pb, X, lo, hi):
        ends = [-1e9] * nrows
        row_h = (h - 6) / nrows
        for word, t0, t1 in words:
            if t1 <= pa or t0 >= pb:
                continue
            x0 = X(t0)
            d.line((max(lo, x0), y + h - 3, min(hi, max(x0 + 1, X(t1))), y + h - 3), fill=(130, 175, 130), width=2)
            if x0 < lo:
                continue
            for r in range(nrows):
                if x0 >= ends[r] + 4 and x0 + _tw(font, word) <= hi:
                    d.text((x0, y + 1 + r * row_h), word, fill=TEXT, font=font)
                    ends[r] = x0 + _tw(font, word)
                    shown[0] += 1
                    break
    info.update(count=len(words), words=[[w, _r(x), _r(y)] for w, x, y in words])
    return {'height': h, 'draw': draw, 'info': info, 'shown': shown}


def _ov_loudness_lane(a, b, f10, h, info, ov, spec):
    wav, a0 = ov.src.sound(a, b)
    series, summ = _loudness(wav, a0, a, b, ov.work) if wav else ([], {})
    full = _full(series, a0)
    lo_db, hi_db = float(spec.get('min', -60)), float(spec.get('max', 0))

    def Y(y, v):
        return y + h - 2 - (min(hi_db, max(lo_db, v)) - lo_db) / (hi_db - lo_db) * (h - 4)

    def draw(img, d, y, pa, pb, X, lo, hi):
        step = 10 if (h - 4) * 10 / (hi_db - lo_db) >= 14 else 20
        for db in range(int(math.ceil(lo_db / step) * step), int(hi_db) + 1, step):
            d.line((lo, Y(y, db), hi, Y(y, db)), fill=(55, 55, 64))
            d.text((lo - 26, Y(y, db) - 6), f'{db}', fill=(110, 110, 120), font=f10)
        pm = [(X(t), Y(y, m)) for t, m, s in full if pa <= t <= pb and m is not None]
        ps = [(X(t), Y(y, s)) for t, m, s in full if pa <= t <= pb and s is not None]
        if len(pm) > 1:
            d.line(pm, fill=(75, 95, 125), width=1)
        if len(ps) > 1:
            d.line(ps, fill=(110, 190, 255), width=2)
    info.update(summ)
    info.update(scale=[lo_db, hi_db], lines='short-term (3 s window, bright) and momentary (0.4 s, dim) LUFS',
                rendered_by='melt (export engine), the mix before export loudness finishing')
    info['_series'] = (series, a0)
    return {'height': h, 'draw': draw, 'info': info}


def _ov_beats_lane(a, b, h, info, ov):
    import letitedit.footage.perception as pc
    marks, per_clip, missing = [], [], []
    import letitedit.sound.music as _music
    music_names = {t['name'] for t in _music.music_tracks(ov.script)}
    for t, items in ov.tracks:
        if t.get('kind') != 'audio':
            continue
        for it, s, e in items:
            if 'clip' not in it:
                continue
            if not pc.is_cached('beats', it['clip']):
                if t['name'] in music_names:
                    missing.append(it.get('id'))
                continue
            res = pc.music(it['clip'])
            speed = abs(float(it.get('speed', 1) or 1))
            i0, i1 = float(it.get('in', 0)), float(it.get('out', 0))
            down = set(round(x, 3) for x in res.get('downbeats', []))
            n = 0
            for bt in res.get('beat_times', []):
                if i0 <= bt < i1:
                    tt = s + (bt - i0) / speed
                    if a <= tt <= b:
                        marks.append((tt, round(bt, 3) in down))
                        n += 1
            per_clip.append({'id': it.get('id'), 'clip': os.path.basename(it['clip']), 'bpm': res.get('bpm'),
                             'beats': n})

    def draw(img, d, y, pa, pb, X, lo, hi):
        for tt, down in marks:
            if pa <= tt <= pb:
                x = X(tt)
                d.line((x, y + (2 if down else h // 2), x, y + h - 3), fill=(255, 170, 60) if down else (200, 140, 70))
    info.update(clips=per_clip, without_beat_data=missing, marks='downbeats tall, beats short')
    return {'height': h, 'draw': draw, 'info': info}


def _ov_graphics_lane(a, b, f10, h, info, name, ov, spec):
    spans = []
    for t, items in ov.tracks:
        for it, s, e in items:
            k = _item_kind(it)
            if (name == 'graphics' and k in ('graphic', 'ass', 'vfx')) or (name == 'captions' and k == 'caption'):
                if e > a and s < b:
                    spans.append((s, e, (_item_name(it), ov.color(it), t['name'], it.get('id'))))
    if name == 'captions':
        for cap in ov.script.get('captions', []):
            import letitedit.timeline.edit_script as es
            for q in cap.get('cues', []):
                s, e = es.to_seconds(q['start']), es.to_seconds(q['end'])
                if e > a and s < b:
                    spans.append((s, e, (q['text'].replace('\n', ' / '), KIND_COLOR['caption'], cap['track'], None)))
    packed, nrows = _pack(spans)
    row_h = max(12, int(spec.get('row_h', 14)))
    H = max(h, nrows * row_h + 4)

    def draw(img, d, y, pa, pb, X, lo, hi):
        for r, s, e, (text, col, _, _) in packed:
            if e > pa and s < pb:
                _block(d, X, lo, hi, s, e, y + 2 + r * row_h, y + 2 + (r + 1) * row_h - 2, col, text, f10)
    info['items'] = [{'start': _r(s), 'end': _r(e), 'text': p[0][:120], 'track': p[2], **({'id': p[3]} if p[3] else {})}
                     for s, e, p in sorted(spans, key=lambda x: x[0])]
    return {'height': H, 'draw': draw, 'info': info}


def _ov_gaps_lane(a, b, f10, h, info, ov):
    gaps, pos = [], 0.0
    for it, s, e in ov.main:
        if s > pos + 1e-3:
            gaps.append((pos, s))
        pos = max(pos, e)
    if ov.src.duration > pos + 1e-3:
        gaps.append((pos, ov.src.duration))
    gaps = [(s, e) for s, e in gaps if e > a and s < b]

    def draw(img, d, y, pa, pb, X, lo, hi):
        for s, e in gaps:
            if e > pa and s < pb:
                _block(d, X, lo, hi, s, e, y + 2, y + h - 3, (150, 60, 60), f'{e - s:.2f}s', f10)
    info.update(track=ov.main_name, gaps=[[_r(s), _r(e)] for s, e in gaps])
    return {'height': h, 'draw': draw, 'info': info}


def _ov_recorded_lane(a, b, f10, h, info, ov):
    from datetime import timedelta
    shots = []
    for it, s, e in ov.main:
        if 'clip' not in it:
            continue
        try:
            start = core_tools.rec_start(core_tools.probe(it['clip']))
        except Exception:  # noqa: BLE001
            start = None
        if start is None:
            continue
        i0, i1 = float(it.get('in', 0)), float(it.get('out', 0))
        shots.append((it, s, e, start + timedelta(seconds=i0), start + timedelta(seconds=i1)))
    cuts = []
    for (p, ps, pe, pf, pt), (n, ns, ne, nf, nt) in zip(shots, shots[1:]):
        cuts.append({'at': _r(ns), 'from': p.get('id'), 'to': n.get('id'),
                     'jump_s': _r((nf - pt).total_seconds(), 2), 'gap_on_timeline_s': _r(ns - pe)})

    def draw(img, d, y, pa, pb, X, lo, hi):
        for it, s, e, rf, rt in shots:
            if e > pa and s < pb:
                _block(d, X, lo, hi, s, e, y + 2, y + h // 2 - 1, (60, 70, 92), rf.strftime('%H:%M:%S'), f10,
                       outline=(85, 95, 120))
        last = -1e9
        for c in cuts:
            if pa <= c['at'] <= pb:
                x = X(c['at'])
                d.line((x, y + h // 2, x, y + h - 2), fill=(230, 190, 90))
                t = _jump_text(c['jump_s'])
                if x + 3 + _tw(f10, t) <= hi and x >= last + 4:      # labels where they fit; every jump in info
                    d.text((x + 2, y + h // 2 + 2), t, fill=(230, 190, 90), font=f10)
                    last = x + 2 + _tw(f10, t)
    info.update(shots=[{'id': it.get('id'), 'start': _r(s), 'end': _r(e),
                        'recorded': f"{rf.strftime('%Y-%m-%d %H:%M:%S')}-{rt.strftime('%H:%M:%S')}"}
                       for it, s, e, rf, rt in shots if e > a and s < b],
                cuts=[c for c in cuts if a <= c['at'] <= b],
                jump='recording time from the end of one shot to the start of the next (camera clock)')
    return {'height': h, 'draw': draw, 'info': info}


def _ov_thumbs_lane(a, b, f10, h, info, ov, spec):
    from PIL import Image
    mode = spec.get('from', 'source')
    per_clip = spec.get('per_clip', 'fill')
    cap = int(spec.get('max_per_clip', 20))
    th = h - 4
    folder = ov.work / 'thumbs'
    folder.mkdir(parents=True, exist_ok=True)
    W, H = ov.src.size
    slots = []                      # (item, slot start, slot end, timeline time of its frame)
    for it, s, e in ov.main:
        vs, ve = max(s, a), min(e, b)
        if ve <= vs:
            continue
        if per_clip == 'fill':
            asp = W / H
            if mode != 'render' and 'clip' in it:
                try:
                    pi = core_tools.probe(it['clip'])
                    asp = (pi.get('width') or W) / (pi.get('height') or H)
                except Exception:  # noqa: BLE001
                    pass
            n = max(1, min(cap, int((ve - vs) * ov.scale // max(1.0, th * asp))))
        else:
            n = max(1, int(per_clip))
        for k in range(n):
            sa_, sb_ = vs + k * (ve - vs) / n, vs + (k + 1) * (ve - vs) / n
            slots.append((it, sa_, sb_, (sa_ + sb_) / 2))
    if mode == 'render':
        got = ov.src.frames([t for *_, t in slots], folder)
    else:
        def one(k_slot):
            k, (it, s0, s1, tt) = k_slot
            if 'clip' not in it:
                return None
            s = next(s for x, s, e in ov.main if x is it)
            speed = abs(float(it.get('speed', 1) or 1))
            t = float(it.get('in', 0)) + (tt - s) * speed
            if it.get('reverse'):
                t = float(it.get('out', 0)) - (tt - s) * speed
            return _grab(it['clip'], t, folder / f't_{k:04d}.png', core_tools._kind(it['clip']))
        with ThreadPoolExecutor(max_workers=4) as pool:
            got = list(pool.map(one, enumerate(slots)))
    thumbs = []
    for p_ in got:
        im_ = None
        if p_ and Path(p_).exists():
            with Image.open(p_) as im:
                im = im.convert('RGB')
                im_ = im.resize((max(1, round(im.width * th / im.height)), th), Image.LANCZOS)
        thumbs.append(im_)

    def draw(img, d, y, pa, pb, X, lo, hi):
        for (it, s0, s1, tt), im in zip(slots, thumbs):
            if s1 <= pa or s0 >= pb:
                continue
            x0, x1 = max(lo, X(s0)), min(hi, X(s1))
            wpx = int(x1 - x0) - 1
            if wpx < 1:
                continue
            if im is None:
                _block(d, X, lo, hi, s0, s1, y + 2, y + h - 3, ov.color(it), _item_name(it), f10)
                continue
            if im.width > wpx:
                off = (im.width - wpx) // 2
                im = im.crop((off, 0, off + wpx, im.height))
            img.paste(im, (int(x0), y + 2))
    info.update(source=mode, per_clip=per_clip, frames=sum(1 for im in thumbs if im is not None),
                shows=('frames of each main-track clip at the middle of equal slots of it, '
                       + ('decoded from its source file' if mode == 'source' else 'as the export renders them')
                       + ', each cut to its slot width'),
                files=[str(p_) for p_ in got if p_])
    if per_clip == 'fill':
        info['max_per_clip'] = cap
    return {'height': h, 'draw': draw, 'info': info}


def _ov_lane(name, spec, ov):
    """{'height', 'draw': fn(img, d, y, pa, pb, X, x_lo, x_hi), 'info', 'rows': [(label, y offset)]}"""
    h = int(spec.get('height') or LANE_H[name])
    f10, f11 = _font(10), _font(11)
    info = {'lane': name}
    a, b = ov.a, ov.b
    if name == 'clips':
        return _ov_clips_lane(a, b, f10, f11, h, info, ov)
    if name == 'tracks':
        return _ov_tracks_lane(a, b, f10, info, ov, spec)
    if name == 'speech':
        return _ov_speech_lane(a, b, h, info, ov)
    if name == 'words':
        return _ov_words_lane(a, b, h, info, ov, spec)
    if name == 'loudness':
        return _ov_loudness_lane(a, b, f10, h, info, ov, spec)
    if name == 'beats':
        return _ov_beats_lane(a, b, h, info, ov)
    if name in ('graphics', 'captions'):
        return _ov_graphics_lane(a, b, f10, h, info, name, ov, spec)
    if name == 'gaps':
        return _ov_gaps_lane(a, b, f10, h, info, ov)
    if name == 'recorded':
        return _ov_recorded_lane(a, b, f10, h, info, ov)
    if name == 'thumbs':
        return _ov_thumbs_lane(a, b, f10, h, info, ov, spec)
    raise ValueError(name)


def _tick_s(scale):
    for t in (0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600):
        if t * scale >= 70:
            return t
    return 3600


def overview(project, start=None, end=None, scale=None, lanes=None, width=None, out_dir=None):
    """One picture (or pages) of a whole edit's shape, like an editor's timeline.

    start / end: timeline seconds (default the whole timeline). lanes (top to bottom, default ['thumbs', 'clips',
    'tracks', 'speech', 'words', 'recorded']): 'thumbs' (a frame per main-track clip; {lane: thumbs, from: 'render'}
    for export frames), 'clips' (main-track blocks labelled with their source names and ids, a colour per source
    file), 'tracks' (every track's items, a row per track), 'speech' (voice spans), 'words' (word labels where they
    fit), 'loudness' (short-term LUFS of the mix, rendered by melt), 'beats' (beats of music clips whose files have
    beat data), 'graphics', 'captions', 'gaps' (main track), 'recorded' (when each shot was filmed and the jump in
    recording time at each cut), or dicts {lane, height, ...} (tracks: row_h; words: rows, font; loudness: min, max).
    scale: px per second (default: the range fits `width`). width: page width px (default 2400); a range wider than a
    page continues on more pages.
    Returns ([png bytes per page], info): the lanes drawn with their data, the scale, the time axis, every page's
    file and time range, every main-track clip's span."""
    started = time.monotonic()
    defaults = _defaults(start=(start, 0), end=(end, 'end of the timeline'), lanes=(lanes, OVERVIEW_DEFAULT),
                         width=(width, 2400), scale=(scale, 'fits the range into width'))
    work = _folder(out_dir, 'overview')
    src = _Src('project', project, work)
    total = src.duration
    a = max(0.0, float(start)) if start is not None else 0.0
    b = min(total, float(end)) if end is not None else total
    if b <= a:
        raise ValueError(f'start-end {a}-{b}: nothing of the {total:.2f} s timeline')
    width = int(width or 2400)
    margin = 112
    plot_w = max(100, width - margin - 8)
    scale = float(scale) if scale else plot_w / (b - a)
    page_s = plot_w / scale
    n_pages = max(1, math.ceil((b - a) / page_s - 1e-6))
    specs = _lane_specs(lanes, OVERVIEW_LANES, OVERVIEW_DEFAULT)
    ov = _Ov(src, a, b, work)
    ov.scale = scale
    built = [(sp['lane'], _ov_lane(sp['lane'], sp, ov)) for sp in specs]
    tick = _tick_s(scale)
    ruler = 22
    from PIL import Image, ImageDraw
    images, pages_info = [], []
    for p in range(n_pages):
        pa = a + p * page_s
        pb = min(b, pa + page_s)
        W = margin + int(math.ceil((pb - pa) * scale)) + 8
        H = ruler + sum(l['height'] + 3 for _, l in built) + 2
        img = Image.new('RGB', (W, H), BG)
        d = ImageDraw.Draw(img)
        lo, hi = margin, margin + (pb - pa) * scale

        def X(t, pa=pa):
            return margin + (t - pa) * scale
        k0 = math.ceil(pa / tick - 1e-9)
        k = k0
        while k * tick <= pb + 1e-9:
            t = k * tick
            x = X(t)
            d.line((x, ruler - 6, x, ruler - 1), fill=(160, 160, 170))
            lab = _clock(t, 1 if tick < 1 else 0) if tick < 60 or t % 60 else f'{int(t // 60)}:00'
            d.text((x + 2, 3), lab, fill=(180, 180, 190), font=_font(11))
            k += 1
        d.text((4, 3), f'{_clock(pa, 1)}-{_clock(pb, 1)}', fill=ACCENT, font=_font(11, True))
        y = ruler
        for name, lane in built:
            lh = lane['height']
            d.rectangle((lo, y, hi, y + lh - 1), fill=LANE_BG)
            for c in ov.cuts:
                if pa < c < pb:
                    d.line((X(c), y, X(c), y + lh - 1), fill=(52, 52, 60))
            lane['draw'](img, d, y, pa, pb, X, lo, hi)
            if lane.get('rows'):
                f = _font(lane.get('row_font', 10))
                for text, off in lane['rows']:
                    d.text((4, y + off), _fit(text, f, margin - 8), fill=(170, 170, 180), font=f)
            else:
                d.text((4, y + max(0, lh // 2 - 7)), _fit(name, _font(12, True), margin - 8), fill=(190, 190, 200),
                       font=_font(12, True))
            y += lh + 3
        path = work / f'overview_{p + 1}.png'
        images.append(_save_png(img, path))
        pages_info.append({'file': str(path), 'start': _r(pa), 'end': _r(pb), 'width': W, 'height': H})
    lanes_info = []
    for name, lane in built:
        li = dict(lane['info'])
        series = li.pop('_series', None)
        if series is not None:
            li['short_term_at_ticks'] = [{'t': _r(t), 'short_term': r[1]} for t in
                                         [k * tick for k in range(math.ceil(a / tick), int(b / tick) + 1)]
                                         for r in [_reading(series[0], t, series[1])] if r and r[1] is not None]
        if 'shown' in lane:
            li['labelled'] = lane['shown'][0]
        li['height'] = lane['height']
        lanes_info.append(li)
    clips = [{'id': it.get('id'), 'start': _r(s), 'end': _r(e), 'source': _item_name(it),
              **({'in': it.get('in'), 'out': it.get('out')} if 'clip' in it else {})}
             for it, s, e in ov.main if e > a and s < b]
    info = {**checks.reported(src.path), 'length': _r(total), 'range': [_r(a), _r(b)], 'scale_px_per_s': _r(scale, 4),
            'width': width, 'axis': {'tick_s': tick, 'margin_px': margin, 'page_seconds': _r(page_s),
                                     'x': 'margin_px + (t - page start) * scale_px_per_s'},
            'main_track': ov.main_name, 'lanes': lanes_info, 'clips': clips, 'pages': pages_info,
            'files': [pg['file'] for pg in pages_info], 'folder': str(work), 'defaults': defaults,
            'seconds': round(time.monotonic() - started, 1)}
    return images, info


# ---------------------------------------------------------------------------- stills

def stills(source=None, times=None, project=None, region=None, size=None, out_dir=None, format='png'):
    """Frames of a file or a project as image files.

    source: a video or image file, or a project (.mlt); project: a project (instead of source). times: seconds
    (default: the middle). Project frames are rendered by melt like the export, at the project's size; file frames
    are decoded at the file's size. region: [x0, y0, x1, y1] as 0-1 fractions of the frame or as pixels (any value
    above 1). size: a height px (width follows), [w, h] (scaled to cover w x h, centred, the rest cut off), or
    [w, None] / [None, h]. format: 'png' (default), 'jpg' or 'webp'.
    Returns {'files': [...], 'times', 'region_px', 'size', 'format', 'folder'}."""
    from PIL import Image
    started = time.monotonic()
    if source is None and project is None:
        raise ValueError('source or project is needed')
    src_path = project if project is not None else source
    kind = 'project' if project is not None or _is_project(source) else 'file'
    fmt = str(format or 'png').lower().lstrip('.')
    fmt = {'jpeg': 'jpg'}.get(fmt, fmt)
    if fmt not in ('png', 'jpg', 'webp'):
        raise ValueError("format: 'png', 'jpg' or 'webp'")
    work = _folder(out_dir, 'stills')
    s = _Src(kind, src_path, work / '_raw')
    defaults = _defaults(times=(times, 'the middle'), region=(region, 'whole frame'), size=(size, 'as rendered'),
                         format=(None if format == 'png' else format, 'png'))
    if times is None:
        times = [s.duration / 2 if s.media != 'image' else 0.0]
    elif not isinstance(times, (list, tuple)):
        times = [times]
    times = [min(max(0.0, float(t)), max(0.0, s.duration - 0.02)) if s.media != 'image' else 0.0 for t in times]
    pngs = s.frames(times, work / '_raw')
    files, boxes, sizes = [], [], []
    stem = re.sub(r'[^A-Za-z0-9_-]+', '_', s.path.stem)[:40]
    for k, (t, p) in enumerate(zip(times, pngs), 1):
        if p is None:
            files.append(None)
            continue
        with Image.open(p) as im:
            im = im.convert('RGB')
            box = _box(region, im.width, im.height) if region is not None else [0, 0, im.width, im.height]
            im = im.crop(box)
            if size:
                w0, h0 = im.size
                if isinstance(size, (int, float)):
                    tw, th = max(1, round(w0 * size / h0)), int(size)
                else:
                    sw, sh = (list(size) + [None, None])[:2]
                    if sw and sh:
                        k_ = max(sw / w0, sh / h0)
                        im = im.resize((max(int(sw), round(w0 * k_)), max(int(sh), round(h0 * k_))), Image.LANCZOS)
                        ox, oy = (im.width - int(sw)) // 2, (im.height - int(sh)) // 2
                        im = im.crop((ox, oy, ox + int(sw), oy + int(sh)))
                        tw, th = im.size
                    elif sw:
                        tw, th = int(sw), max(1, round(h0 * sw / w0))
                    else:
                        tw, th = max(1, round(w0 * sh / h0)), int(sh)
                if im.size != (tw, th):
                    im = im.resize((tw, th), Image.LANCZOS)
            out = work / f'{stem}_{k:02d}_{t:.2f}s.{fmt}'.replace(':', '-')
            if fmt == 'jpg':
                im.save(out, 'JPEG', quality=92)
            elif fmt == 'webp':
                im.save(out, 'WEBP', quality=92)
            else:
                im.save(out, 'PNG')
            files.append(str(out))
            boxes.append(box)
            sizes.append(list(im.size))
    return {'files': files, 'times': [_r(t) for t in times], 'source': str(s.path), 'kind': s.media,
            'region_px': boxes, 'size': sizes, 'format': fmt, 'folder': str(work),
            'rendered_by': 'melt (export engine)' if kind == 'project' else 'ffmpeg', 'defaults': defaults,
            'seconds': round(time.monotonic() - started, 1)}
