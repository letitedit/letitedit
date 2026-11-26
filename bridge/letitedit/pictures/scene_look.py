"""Frames of a code scene from a browser that stays open (the AI's fast look at a scene).

`draw(page_html, times, out_dir, width, height)` asks a helper (motion\\runtime\\scene-look.js, run with the same Node
and Edge or Chrome as motion clips) for one transparent PNG per time. The helper closes itself after IDLE_S seconds
without a job and when this process ends; one helper at a time per tool server. Nothing here layers the picture: the
frames go into the project's own timeline (code_scenes.looks_path) and melt puts the cut-out and captions over them.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import atexit
import json
import queue
import subprocess
import threading
import time
from pathlib import Path

import letitedit.pictures.motion as motion

IDLE_S = 300
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
SCRIPT = _paths.CODE_ROOT / 'motion' / 'runtime' / 'scene-look.js'
_LOCK = threading.Lock()
_helper = None


class _Helper:
    def __init__(self):
        why = motion.available()
        if why:
            raise RuntimeError(why)
        self.browser = motion.browser_exe()
        import letitedit.core.render_lock as render_lock
        self.process = render_lock.popen_worker([motion.node_exe(), str(SCRIPT), self.browser, str(IDLE_S)],
                                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                stderr=subprocess.DEVNULL, text=True, encoding='utf-8', bufsize=1,
                                                cwd=str(SCRIPT.parent), env=motion.clean_env(),
                                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.lines = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.started = self.ask_line(60)

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def ask_line(self, timeout):
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty:
            self.kill()
            raise TimeoutError(f'the scene helper did not answer in {timeout:.0f} s') from None
        if line is None:
            raise RuntimeError('the scene helper stopped')
        answer = json.loads(line)
        if answer.get('fatal'):
            raise RuntimeError('the scene helper could not start: ' + answer['fatal'])
        return answer

    def alive(self):
        return self.process.poll() is None

    def kill(self):
        try:
            self.process.kill()
        except OSError:
            pass

    def close(self):
        try:
            self.process.stdin.write('{"quit": true}\n')
            self.process.stdin.flush()
            self.process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            self.kill()


def close():
    """Stop the helper now (it also stops itself when idle and when this process ends)."""
    global _helper
    with _LOCK:
        if _helper:
            _helper.close()
        _helper = None


atexit.register(close)


def running():
    return bool(_helper and _helper.alive())


def draw(page_html, times, out_dir, width, height, timeout=None):
    """{'frames': [png or None per time], 'errors': [...], 'mode': 'canvas'|'screenshot', 'seconds', 'started': bool}."""
    global _helper
    started = time.monotonic()
    with _LOCK:
        fresh = False
        if not (_helper and _helper.alive()):
            _helper = _Helper()
            fresh = True
        job = {'page': str(page_html), 'times': [float(t) for t in times], 'out': str(out_dir),
               'width': int(width), 'height': int(height)}
        try:
            _helper.process.stdin.write(json.dumps(job) + '\n')
            _helper.process.stdin.flush()
            answer = _helper.ask_line(timeout or 60 + 0.5 * len(times))
        except (OSError, TimeoutError, RuntimeError):
            _helper.kill()
            _helper = None
            raise
    answer['seconds'] = round(time.monotonic() - started, 2)
    answer['started'] = fresh
    return answer


def problems(answer):
    """What a machine can tell without looking: page errors, a blank scene, a scene that does not move."""
    import numpy as np
    from PIL import Image
    found = list(answer.get('errors') or [])
    arrays = []
    for file in answer.get('frames') or []:
        if not file:
            arrays.append(None)
            continue
        with Image.open(file) as image:
            arrays.append(np.asarray(image.convert('RGBA').resize((135, 240), Image.Resampling.BILINEAR), dtype=np.float32))
    if any(a is None for a in arrays):
        found.append('a frame could not be drawn')
    good = [a for a in arrays if a is not None]
    if good:
        if max(float((a[..., 3] > 8).mean()) for a in good) < 0.01:
            found.append('the scene is blank: nothing is drawn in any frame')
        moves = [float(np.abs(x - y).mean()) for x, y in zip(good, good[1:])]
        if moves and max(moves) < 0.2:
            found.append('the scene does not move: every drawn frame is the same')
    return found
