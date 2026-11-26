"""Offline OCR with Windows' own text recognizer (Windows.Media.Ocr; part of Windows 10/11, nothing to download).

    available()                      -> (True, 'en-US') or (False, why)
    read(paths, variants=('raw', 'light'))
                                     -> [{path, w, h, lines: [{text, box: [x0, y0, x1, y1] (fractions), words: [...],
                                         variant}]}] one per path, lines from every variant merged
    Reader()                         a running worker (context manager) for many calls

How it works: bridge/ocr_worker.ps1 runs in Windows PowerShell 5.1 (the only PowerShell that loads WinRT types
without extra packages) and stays running; image paths go in on stdin, one JSON line per image comes back. One worker
reads about 10-25 images a second at 540 px wide.

Variants. Captions in social video are usually light text with a dark outline or shadow over moving footage; the
recognizer reads the raw frame poorly there ("bucl«s" for "bucks") and drops words over busy backgrounds. The 'light'
variant is a mask of bright, low-saturation pixels (white and pale fills) drawn black on white, which it reads cleanly;
'colour' masks bright saturated fills (yellow / green / pink highlight words); 'dark' masks dark text on light plates.
Lines found in several variants are merged (the variant with the most letters wins).
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import json
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
WORKER = _paths.BRIDGE / 'ocr_worker.ps1'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
POWERSHELL = os.environ.get('LETITEDIT_POWERSHELL') or str(
    Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe')
VARIANTS = ('raw', 'light', 'colour', 'dark')
_avail = {}


class OcrUnavailable(RuntimeError):
    pass


class Reader:
    """A running OCR worker. with Reader() as r: r.read_one(path) -> raw worker dict."""

    def __init__(self, lang='', timeout=60):
        if os.name != 'nt':
            raise OcrUnavailable('Windows OCR needs Windows')
        if not Path(POWERSHELL).exists():
            raise OcrUnavailable(f'Windows PowerShell not found at {POWERSHELL}')
        args = [POWERSHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(WORKER)]
        if lang:
            args += ['-Lang', lang]
        import letitedit.core.render_lock as render_lock
        self.p = render_lock.popen_worker(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          creationflags=NO_WINDOW, text=True, encoding='utf-8', errors='replace',
                                          bufsize=1)
        self._q = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        first = self._get(timeout)
        if not first or not first.get('ready'):
            err = (first or {}).get('error') or self._stderr()
            self.close()
            raise OcrUnavailable(f'Windows OCR did not start: {err}')
        self.lang = first.get('lang')
        self.max_dim = int(first.get('max_dim') or 10000)

    def _pump(self):
        for line in self.p.stdout:
            line = line.strip()
            if line.startswith('{'):
                try:
                    self._q.put(json.loads(line))
                except ValueError:
                    pass
        self._q.put(None)

    def _stderr(self):
        try:
            return (self.p.stderr.read() or '')[-600:]
        except Exception:  # noqa: BLE001
            return ''

    def _get(self, timeout):
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def read_one(self, path, timeout=30):
        if self.p.poll() is not None:
            raise OcrUnavailable(f'the OCR worker stopped: {self._stderr()}')
        self.p.stdin.write(str(Path(path).resolve()) + '\n')
        self.p.stdin.flush()
        out = self._get(timeout)
        if out is None:
            raise OcrUnavailable('the OCR worker did not answer')
        return out

    def close(self):
        try:
            if self.p.poll() is None:
                self.p.stdin.write('quit\n')
                self.p.stdin.flush()
                self.p.wait(5)
        except Exception:  # noqa: BLE001
            pass
        if self.p.poll() is None:
            self.p.kill()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def available():
    """(True, language tag) when Windows OCR runs here, else (False, the reason). Cached per process."""
    if 'r' not in _avail:
        try:
            with Reader() as r:
                _avail['r'] = (True, r.lang)
        except Exception as e:  # noqa: BLE001
            _avail['r'] = (False, f'{type(e).__name__}: {e}')
    return _avail['r']


# ------------------------------------------------------------------ variants

def masks(bgr):
    """{variant: uint8 image to read} for a BGR frame: 'raw' (the frame), 'light' / 'colour' / 'dark' text masks as
    black text on white."""
    import cv2
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1].astype(np.int16), hsv[:, :, 2].astype(np.int16)
    out = {'raw': bgr}
    light = ((v > 200) & (s < 70)).astype(np.uint8) * 255
    out['light'] = 255 - light
    colour = ((v > 170) & (s >= 110)).astype(np.uint8) * 255
    out['colour'] = 255 - colour
    dark = (v < 60).astype(np.uint8) * 255
    out['dark'] = 255 - dark
    return out


def _clean(text):
    return re.sub(r'\s+', ' ', str(text or '')).strip()


def _letters(text):
    return sum(ch.isalnum() for ch in text)


def _box_of(words, w, h):
    x0 = min(wd['x'] for wd in words) / w
    y0 = min(wd['y'] for wd in words) / h
    x1 = max(wd['x'] + wd['w'] for wd in words) / w
    y1 = max(wd['y'] + wd['h'] for wd in words) / h
    return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def plausible(text):
    """False for OCR noise: no letters/digits, or mostly symbols."""
    t = _clean(text)
    n = _letters(t)
    return n >= 1 and n >= 0.5 * len(t.replace(' ', ''))


_PLAIN = set(" .,'!?$%&:;-\"()#@/+*’‘“”")


def quality(text, ascii_letters=True):
    """Letters and digits, less 3 per character that is neither a letter, a digit nor common punctuation (the marks
    the recognizer makes of a letter it could not read), less 3 per word that glues digits to letters ('4coming';
    '3rd', '10am', '2x' are fine) and, for English (ascii_letters), less 2 per accented letter."""
    t = _clean(text)
    q = _letters(t) - 3 * sum(1 for ch in t if not ch.isalnum() and ch not in _PLAIN)
    for w in re.findall(r'[0-9A-Za-zÀ-ɏ]+', t):
        if re.search(r'\d', w) and re.search(r'[A-Za-zÀ-ɏ]', w) and not re.fullmatch(
                r'\d+(st|nd|rd|th|s|am|pm|k|m|x|p|d|v|mm|cm|km|kg|lb|lbs|hz|fps|gb|mb|tb)', w, re.I):
            q -= 3
    if ascii_letters:
        q -= 2 * sum(1 for ch in t if ch.isalpha() and ord(ch) > 127)
    return q


def _inside(a, b):
    """Share of box a that lies inside box b."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max(1e-9, (a[2] - a[0]) * (a[3] - a[1]))
    return ix * iy / area


def merge_lines(per_variant):
    """[(variant, lines)] -> lines with boxes; a line overlapping another (IoU > 0.3, or mostly inside it) from another
    variant is one line: the reading with the best quality() wins (ties: the earlier variant)."""
    out = []
    for variant, lines in per_variant:
        for ln in lines:
            if not plausible(ln['text']):
                continue
            hit = next((o for o in out if iou(o['box'], ln['box']) > 0.3 or _inside(o['box'], ln['box']) > 0.7
                        or _inside(ln['box'], o['box']) > 0.7), None)
            if hit is None:
                out.append({**ln, 'variant': variant, 'seen_in': [variant], 'alts': {variant: ln['text']}})
            else:
                hit['seen_in'].append(variant)
                hit['alts'].setdefault(variant, ln['text'])
                if quality(ln['text']) > quality(hit['text']):
                    seen, alts = hit['seen_in'], hit['alts']
                    hit.clear()
                    hit.update({**ln, 'variant': variant, 'seen_in': seen, 'alts': alts})
    return sorted(out, key=lambda ln: (ln['box'][1], ln['box'][0]))


def _lines(raw):
    w, h = max(1, int(raw.get('w') or 1)), max(1, int(raw.get('h') or 1))
    out = []
    for ln in raw.get('lines') or []:
        words = [wd for wd in ln.get('words') or [] if wd.get('text')]
        if not words:
            continue
        out.append({'text': _clean(ln.get('text')), 'box': _box_of(words, w, h),
                    'words': [{'text': wd['text'], 'box': [round(wd['x'] / w, 4), round(wd['y'] / h, 4),
                                                          round((wd['x'] + wd['w']) / w, 4),
                                                          round((wd['y'] + wd['h']) / h, 4)]} for wd in words]})
    return out


def read(paths, variants=('raw', 'light'), reader=None, scratch=None):
    """OCR of image files. variants: which images to read per file (VARIANTS); masks are written beside `scratch`
    (default: a temp folder) and removed. Returns one dict per path: {path, w, h, lines, ms, error?}."""
    import cv2
    import tempfile
    own = reader is None
    r = reader or Reader()
    tmp = Path(scratch or tempfile.mkdtemp(prefix='letitedit_ocr_'))
    tmp.mkdir(parents=True, exist_ok=True)
    out = []
    try:
        for k, p in enumerate(paths):
            t0 = time.monotonic()
            bgr = cv2.imread(str(p))
            if bgr is None:
                out.append({'path': str(p), 'error': 'not an image', 'lines': []})
                continue
            h, w = bgr.shape[:2]
            per = []
            ms = masks(bgr) if any(v != 'raw' for v in variants) else {'raw': bgr}
            for v in variants:
                if v == 'raw':
                    raw = r.read_one(p)
                else:
                    f = tmp / f'm{k}_{v}.png'
                    cv2.imwrite(str(f), ms[v])
                    raw = r.read_one(f)
                    try:
                        f.unlink()
                    except OSError:
                        pass
                if raw.get('error'):
                    continue
                per.append((v, _lines(raw)))
            out.append({'path': str(p), 'w': w, 'h': h, 'lines': merge_lines(per),
                        'ms': int((time.monotonic() - t0) * 1000)})
    finally:
        if own:
            r.close()
        try:
            tmp.rmdir()
        except OSError:
            pass
    return out
