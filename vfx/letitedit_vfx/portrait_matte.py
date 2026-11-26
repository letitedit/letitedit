"""Portrait matte shared by made VFX items and analysis.

Official BiRefNet-lite runs on CUDA when available; cleaned MODNet is the
fallback. Each shot has independent temporal history.

What the model and the clean-up make for one picture depends on that picture alone, so it is kept once per picture
(a hash of the decoded frame, so a piece, a trim or a reorder of the same footage finds it, and a frame that decodes
differently simply misses). The temporal smoothing depends on the shot and runs again on every use: a reused frame
ends up exactly as a newly computed one. fill() computes what a whole plan is missing as one job with one model load.
"""

import contextlib
import contextvars
import functools
import hashlib
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from . import analyze

_cache = contextvars.ContextVar('portrait_matte_cache', default=None)
# Called after each frame the model had to draw (nothing is running then): lets the caller give up a shared lock between
# frames. The matte is cached per frame, so the run carries on where it was.
between_frames = contextvars.ContextVar('portrait_matte_between_frames', default=None)
MATTE_VERSION = 4
FALLBACKS = 0   # how many times BiRefNet was unavailable and cleaned MODNet stood in
STORE_GB = 20.0   # the kept mattes' size limit (LETITEDIT_MATTE_CACHE_GB); the ones used longest ago go first


def store_root():
    from . import config
    return config.LETITEDIT_ROOT / 'cache' / 'portrait-mattes' / f'frames-v{MATTE_VERSION}'


@contextlib.contextmanager
def cache_for(source=None, start=None, frames=None, fps=None, width=None, height=None, settings=None):
    """Inside this block mattes are kept per picture and found again by any effect, piece or trim of the same footage.
    The arguments no longer matter: the picture itself is the key."""
    token = _cache.set(store_root())
    try:
        yield
    finally:
        _cache.reset(token)


def _frame_path(folder, frame):
    key = hashlib.sha1(np.ascontiguousarray(frame).data).hexdigest()
    height, width = frame.shape[:2]
    return folder / f'{width}x{height}' / key[:2] / f'{key[2:]}.png'


def _read_matte(path):
    try:
        with Image.open(path) as image:
            matte = np.asarray(image, np.float32) / 65535.0
    except (OSError, ValueError):
        return None
    with contextlib.suppress(OSError):
        os.utime(path)   # used now: the size limit removes what was used longest ago
    return matte


def _quantise(matte):
    """As stored: 16 bits. A new matte goes through this too, so a reused frame is the same as a new one to the bit."""
    return np.round(np.clip(matte, 0, 1) * 65535).astype(np.uint16)


def _write_matte(path, stored):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp')
    Image.fromarray(stored).save(temp, format='PNG')
    temp.replace(path)


def prune_store(limit_gb=None):
    """Keep the store under its limit: the mattes used longest ago go first. Returns how many were removed."""
    if limit_gb is None:
        limit_gb = float(os.environ.get('LETITEDIT_MATTE_CACHE_GB') or STORE_GB)
    files, total = [], 0
    for folder, _, names in os.walk(store_root()):
        for name in names:
            path = os.path.join(folder, name)
            with contextlib.suppress(OSError):
                st = os.stat(path)
                files.append((st.st_mtime, st.st_size, path))
                total += st.st_size
    limit = limit_gb * 1024 ** 3
    removed = 0
    if total > limit:
        files.sort()
        for _, size, path in files:
            if total <= limit * .9:
                break
            with contextlib.suppress(OSError):
                os.unlink(path)
                total -= size
                removed += 1
    return removed + prune_old_layout()


def prune_old_layout(idle_hours=1.0):
    """T71: before the mattes were kept per picture (T61) they were kept per piece, one 24-character folder each beside
    frames-vN. Nothing reads those any more; a folder whose files nobody has touched for `idle_hours` goes. Returns how many
    folders were removed."""
    import shutil
    parent = store_root().parent
    removed = 0
    try:
        folders = [d for d in parent.iterdir() if d.is_dir() and re.fullmatch(r'[0-9a-f]{24}', d.name)]
    except OSError:
        return 0
    for folder in folders:
        newest = 0.0
        for walked, _, names in os.walk(folder):
            for name in names:
                with contextlib.suppress(OSError):
                    newest = max(newest, os.stat(os.path.join(walked, name)).st_mtime)
        with contextlib.suppress(OSError):
            newest = max(newest, folder.stat().st_mtime)
        if time.time() - newest > idle_hours * 3600:
            shutil.rmtree(folder, ignore_errors=True)
            removed += not folder.exists()
    return removed


@functools.lru_cache(maxsize=1)
def _gpu_available():
    try:
        result = subprocess.run(['nvidia-smi', '-L'], capture_output=True, timeout=5)
        return result.returncode == 0 and b'GPU ' in result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def fill_enclosed_holes(matte):
    """Fill small enclosed holes in the solid person; leave open arm gaps alone."""
    m = np.asarray(matte, dtype=np.float32)
    solid = (m >= 0.55).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(1 - solid, connectivity=8)
    if n <= 1:
        return m
    h, w = m.shape
    border = set(np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1]))))
    limit = max(16, int(h * w * 0.012))
    repair = np.zeros_like(solid)
    for i in range(1, n):
        if i not in border and stats[i, cv2.CC_STAT_AREA] <= limit:
            repair[labels == i] = 1
    if not repair.any():
        return m
    # A soft one-pixel edge avoids a hard outline around the filled region.
    repair = cv2.GaussianBlur(repair.astype(np.float32), (0, 0), 0.8)
    return np.maximum(m, repair).astype(np.float32)


def clean_biref(frame, matte, soft):
    """BiRefNet's raw matte with MODNet's soft detail near its silhouette (soft may be None: no detail to add)."""
    m = matte
    if soft is not None:
        # MODNet's soft detail helps hair and a moving fingertip only near
        # BiRefNet's silhouette. Keep BiRefNet's stable body untouched.
        radius = max(5, int(round(min(m.shape) * .018)) | 1)
        near = cv2.dilate((m > .35).astype(np.uint8), np.ones((radius, radius), np.uint8)) > 0
        boundary = near & (m < .98)
        old, detail = m[boundary], soft[boundary]
        m[boundary] = np.maximum(old, detail * .50) * .82 + detail * .18
    # Small blur of alpha only; hard interior stays opaque.
    blur = cv2.GaussianBlur(m, (0, 0), .8)
    edge = (m > .01) & (m < .99)
    m[edge] = .72 * m[edge] + .28 * blur[edge]
    return m


def keep_subject(m):
    m = fill_enclosed_holes(m)

    # Keep only the principal connected subject and its soft edge.
    core = (m > 0.3).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(core, connectivity=8)
    if n > 2:
        areas = stats[1:, cv2.CC_STAT_AREA]
        keep = np.zeros(n, np.uint8)
        keep[1:] = areas >= areas.max() * .15
        region = cv2.dilate(keep[labels], np.ones((9, 9), np.uint8))
        m *= region
    return m


class MatteStream:
    """Per-shot BiRefNet matte, with soft MODNet detail and a safe fallback."""

    def __init__(self, ref=512, smooth=0.55, tighten=0.06, model='auto'):
        self.ref, self.smooth, self.tighten = ref, smooth, tighten
        self.prev = self.prev_frame = None
        self.model = model
        self.worker = None
        self.failed = False
        self.modnet_ready = False
        base = _cache.get()
        self.cache = _settings_folder(base, model, ref, tighten) if base else None

    def _raw(self, frame):
        if self.model != 'modnet' and not self.failed and _gpu_available():
            try:
                if self.worker is None:
                    if not _worker_ready():
                        raise RuntimeError('official BiRefNet-lite is not ready')
                    from .birefnet import MatteWorker
                    self.worker = MatteWorker()
                return self.worker(frame)
            except Exception as ex:
                import sys
                print(f'[letitedit cut-out] BiRefNet unavailable ({type(ex).__name__}: {ex}); '
                      'using cleaned MODNet', file=sys.stderr)
                self.failed = True
                global FALLBACKS
                FALLBACKS += 1
                if self.worker is not None:
                    self.worker.close()
                    self.worker = None
        self._ensure_modnet()
        return analyze.matte(Image.fromarray(frame), ref=self.ref)

    def _ensure_modnet(self):
        if self.modnet_ready:
            return
        from . import config
        if not (config.MODELS / 'modnet.onnx').is_file():
            import sys
            bridge = config.LETITEDIT_ROOT / 'bridge'
            if bridge.is_dir() and str(bridge) not in sys.path:
                sys.path.insert(0, str(bridge))
            import first_use
            first_use.need(models=['modnet'], feature='person cut-out fallback')
        self.modnet_ready = True

    def _picture(self, frame, path=None):
        """What this frame alone makes: (matte, whether the model had to draw it now)."""
        if path:
            m = _read_matte(path)
            if m is not None:
                return m, False
        m = self._raw(frame)
        used_biref = self.worker is not None and not self.failed
        if used_biref:
            m = np.array(m, np.float32)
            try:
                if not SOFT:
                    raise RuntimeError('soft detail left out')
                self._ensure_modnet()
                soft = analyze.matte(Image.fromarray(frame), ref=self.ref)
            except Exception:
                soft = None
            m = clean_biref(frame, m, soft)
        if self.tighten and not used_biref:
            m = np.clip((m - self.tighten) / (1 - 2 * self.tighten), 0, 1)
        m = keep_subject(m)
        if used_biref:
            stored = _quantise(m)
            if path:
                _write_matte(path, stored)
            m = stored.astype(np.float32) / 65535.0
        return m, used_biref

    def _in_time(self, frame, m):
        """The shot's own history over this frame's matte; it starts afresh with each stream."""
        if self.prev is not None:
            # A drop within a stable shirt or face is a model error.  Changed
            # pixels at a moving arm/edge follow the new frame immediately.
            change = cv2.absdiff(np.ascontiguousarray(frame), self.prev_frame)
            blue, green, red = cv2.split(change)
            changed = cv2.max(cv2.max(blue, green), red)
            inset = max(5, int(round(min(m.shape) * .02)) | 1)
            previous_inside = cv2.erode((self.prev > 0.75).astype(np.uint8),
                                        np.ones((inset, inset), np.uint8)) > 0
            dropout = (m < self.prev - 0.22) & previous_inside & (changed < 19)
            if dropout.any():
                m[dropout] = np.maximum(m[dropout], self.prev[dropout] * 0.97)
            d = np.abs(m - self.prev)
            near = (d < 0.2) & (d > 0)     # the only pixels the blend can change
            m[near] = (m[near].astype(np.float64) * (1 - self.smooth)
                       + self.prev[near].astype(np.float64) * self.smooth).astype(np.float32)
            m = fill_enclosed_holes(m)
        self.prev, self.prev_frame = m, frame.copy()
        return m

    def __call__(self, frame):
        m, drew = self._picture(frame, _frame_path(self.cache, frame) if self.cache else None)
        m = self._in_time(frame, m)
        pause_point = between_frames.get()
        if pause_point is not None and drew:
            pause_point()
        return m

    def __del__(self):
        worker = getattr(self, 'worker', None)
        if worker is not None:
            worker.close()


# T80: with a graphics card BiRefNet draws the matte alone. MODNet's soft edge detail on top cost 25% of the time (150 s against 112 s
# for 8 s in one lock hold) and on the busiest 8 s of IMG_0014 (hands crossing, hair) the two differ on 0.065% of the frame on average,
# 0.55% at worst, along a thin edge, and BiRefNet alone is not clearly worse (`tests/t80/compare_alpha.py`). 4 Nov: the newer
# cut-out was "significantly better" than the older, so MODNet is not added to it. LETITEDIT_MATTE_SOFT=1 puts the detail back.
# A PC with no NVIDIA card has no BiRefNet and still gets MODNet as the matte itself, as before; that path doesn't read this.
# Mattes are kept in a folder of their own for each setting.
SOFT = os.environ.get('LETITEDIT_MATTE_SOFT', '0') == '1'


def _settings_folder(base, model, ref, tighten):
    return base / (f'{model}-{ref}-{tighten:g}' + ('' if SOFT else '-nosoft'))


def _worker_ready():
    import sys
    root = Path(__file__).resolve().parents[2]
    bridge = root / 'bridge'
    if bridge.is_dir() and str(bridge) not in sys.path:
        sys.path.insert(0, str(bridge))
    import first_use
    return bool(first_use.optional(models=['birefnet-lite-official'], env='models', feature='person cut-out'))


def ahead(mattes, frames, depth=3):
    """(frame, matte) for each frame, with the decoding, hashing and reading of kept mattes done ahead on a thread of
    its own. The results are what mattes(frame) gives; only the waiting is shorter."""
    if not mattes.cache:
        for frame in frames:
            yield frame, mattes(frame)
        return
    items = queue.Queue(depth)
    stop = threading.Event()

    def read():
        try:
            for frame in frames:
                path = _frame_path(mattes.cache, frame)
                ready = _read_matte(path)
                while not stop.is_set():
                    try:
                        items.put((frame, path, ready), timeout=.5)
                        break
                    except queue.Full:
                        pass
                if stop.is_set():
                    return
            items.put(None)
        except BaseException as ex:  # noqa: BLE001 - raised again where the frames are used
            items.put(ex)

    thread = threading.Thread(target=read, daemon=True, name='matte-ahead')
    thread.start()
    pause_point = between_frames.get()
    try:
        while True:
            item = items.get()
            if item is None:
                return
            if isinstance(item, BaseException):
                raise item
            frame, path, m = item
            drew = False
            if m is None:
                m, drew = mattes._picture(frame, path)
            m = mattes._in_time(frame, m)
            if pause_point is not None and drew:
                pause_point()
            yield frame, m
    finally:
        stop.set()
        thread.join(5)


@contextlib.contextmanager
def behind(work, depth=3):
    """A function that hands its argument to work(item), in order, on a thread of its own, so a slow writer doesn't hold
    up what comes before it. Leaving the block waits for the rest; an error in work is raised here."""
    items = queue.Queue(depth)
    errors = []

    def run():
        while (item := items.get()) is not None:
            if errors:
                continue
            try:
                work(item)
            except BaseException as ex:  # noqa: BLE001 - raised again in the caller
                errors.append(ex)

    thread = threading.Thread(target=run, daemon=True, name='matte-behind')
    thread.start()

    def give(item):
        if errors:
            raise errors[0]
        items.put(item)
    try:
        yield give
    finally:
        items.put(None)
        thread.join()
    if errors:
        raise errors[0]


def fill(runs, reader, ref=512, tighten=0.06, model='auto', stall_s=60.0, chunk=120):
    """Make what `runs` are missing, as one job with one model load, so the effects that follow only read.
    runs: each is reader's arguments; reader(*run) gives its frames. Nothing it can't do is an error: frames it leaves
    are computed as they are used, with the usual fallback. Returns {frames, drawn, kept, seconds, stopped?}."""
    started = time.monotonic()
    out = {'frames': 0, 'drawn': 0, 'kept': 0}
    if model == 'modnet' or not _gpu_available():
        return {**out, 'stopped': 'no GPU'}
    folder = _settings_folder(store_root(), model, ref, tighten)
    state = {'worker': None, 'error': None, 'last': time.monotonic(), 'pending': 0}
    changed = threading.Condition()
    sent, received, cleaned = queue.Queue(8), queue.Queue(4), queue.Queue(4)
    slots = threading.Semaphore(6)
    pause_point = between_frames.get()
    done = threading.Event()

    def beat():
        state['last'] = time.monotonic()

    def fail(ex):
        with changed:
            if state['error'] is None:
                state['error'] = f'{type(ex).__name__}: {ex}'
            changed.notify_all()
        done.set()

    def put(where, item):
        while not done.is_set():
            try:
                where.put(item, timeout=.5)
                return True
            except queue.Full:
                pass
        return False

    def read():
        try:
            seen, since_pause = set(), 0
            for run in runs:
                for frame in reader(*run):
                    if done.is_set():
                        return
                    out['frames'] += 1
                    path = _frame_path(folder, frame)
                    if path in seen or path.is_file():
                        out['kept'] += 1
                        beat()
                        continue
                    seen.add(path)
                    if state['worker'] is None:
                        if not _worker_ready():
                            raise RuntimeError('official BiRefNet-lite is not ready')
                        from .birefnet import MatteWorker
                        state['last'] = float('inf')    # loading the model has its own time limit
                        state['worker'] = MatteWorker()
                        beat()
                    while not slots.acquire(timeout=.5):
                        if done.is_set():
                            return
                    with changed:
                        state['pending'] += 1
                    state['worker'].send(frame)
                    if not put(sent, (frame, path)):
                        return
                    since_pause += 1
                    if pause_point is not None and since_pause >= chunk:
                        since_pause = 0                 # nothing may be running while the lock is given up
                        with changed:
                            while state['pending'] and not done.is_set():
                                changed.wait(.5)
                        if done.is_set():
                            return
                        state['last'] = float('inf')    # waiting for the lock is no stall
                        pause_point()
                        beat()
        except BaseException as ex:  # noqa: BLE001
            fail(ex)
        finally:
            sent_end.set()

    def receive():
        try:
            while True:
                try:
                    item = sent.get(timeout=.2)
                except queue.Empty:
                    if sent_end.is_set() or done.is_set():
                        return
                    continue
                if done.is_set():
                    return
                frame, path = item
                matte = np.array(state['worker'].receive(frame), np.float32)
                beat()
                slots.release()
                if not put(received, (frame, matte, path)):
                    return
        except BaseException as ex:  # noqa: BLE001
            fail(ex)
        finally:
            received_end.set()

    def detail():
        # MODNet stays on this one thread: two sessions at once can bring down a DirectML provider
        try:
            from . import config
            ready = SOFT and (config.MODELS / 'modnet.onnx').is_file()
            while True:
                try:
                    item = received.get(timeout=.2)
                except queue.Empty:
                    if received_end.is_set() or done.is_set():
                        return
                    continue
                if done.is_set():
                    return
                frame, matte, path = item
                soft = None
                if ready:
                    try:
                        soft = analyze.matte(Image.fromarray(frame), ref=ref)
                    except Exception:
                        soft = None
                if not put(cleaned, (frame, matte, soft, path)):
                    return
        except BaseException as ex:  # noqa: BLE001
            fail(ex)
        finally:
            detail_end.set()

    def finish():
        try:
            while True:
                try:
                    item = cleaned.get(timeout=.2)
                except queue.Empty:
                    if detail_end.is_set() or done.is_set():
                        return
                    continue
                if done.is_set():
                    return
                frame, matte, soft, path = item
                _write_matte(path, _quantise(keep_subject(clean_biref(frame, matte, soft))))
                out['drawn'] += 1
                beat()
                with changed:
                    state['pending'] -= 1
                    changed.notify_all()
        except BaseException as ex:  # noqa: BLE001
            fail(ex)

    sent_end, received_end, detail_end = threading.Event(), threading.Event(), threading.Event()
    threads = [threading.Thread(target=read, daemon=True, name='matte-read'),
               threading.Thread(target=receive, daemon=True, name='matte-receive'),
               threading.Thread(target=detail, daemon=True, name='matte-detail'),
               threading.Thread(target=finish, daemon=True, name='matte-finish-1'),
               threading.Thread(target=finish, daemon=True, name='matte-finish-2')]
    for thread in threads:
        thread.start()
    try:
        while any(t.is_alive() for t in threads):
            threads[0].join(.5)
            if not done.is_set() and time.monotonic() - state['last'] > stall_s:
                fail(TimeoutError(f'the model took over {stall_s:g} seconds for a frame'))
            if done.is_set():
                if state['worker'] is not None:   # ends a read waiting on it
                    state['worker'].stop()
                for t in threads:
                    t.join(3)
                break
    finally:
        if state['worker'] is not None:
            state['worker'].close()
    if state['error']:
        out['stopped'] = state['error']
    out['seconds'] = round(time.monotonic() - started, 1)
    return out
