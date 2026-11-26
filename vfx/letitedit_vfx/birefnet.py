"""Official BiRefNet-lite matte on CUDA, with no torch in the bridge process."""

import os
import struct
import subprocess
import threading
from pathlib import Path

import numpy as np

from . import config


def _read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        part = stream.read(size - len(data))
        if not part:
            raise RuntimeError('BiRefNet worker ended unexpectedly')
        data.extend(part)
    return bytes(data)


def _greeting(proc, timeout=120):  # 8 s when warm; over 25 s on a cold first load
    outcome = {}
    def read():
        try:
            n = struct.unpack('<I', _read_exact(proc.stdout, 4))[0]
            if n > 100:
                raise RuntimeError('invalid BiRefNet worker greeting')
            outcome['value'] = _read_exact(proc.stdout, n)
        except Exception as ex:
            outcome['error'] = ex
    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError(f'BiRefNet worker did not start within {timeout} seconds')
    if 'error' in outcome:
        raise outcome['error']
    return outcome['value']


def _stop_tree(proc):
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                       capture_output=True, timeout=10)
    else:
        proc.kill()
    proc.wait()


class MatteWorker:
    def __init__(self):
        root = config.LETITEDIT_ROOT
        model = config.MODELS / 'birefnet-lite-official'
        if not (model / 'model.safetensors').is_file():
            raise FileNotFoundError('official BiRefNet-lite weights are unavailable')
        models_env = root / 'envs' / 'models'
        music_env = root / 'envs' / 'music_acestep'
        override = os.environ.get('LETITEDIT_BIREFNET_PYTHON')
        # The music CUDA wheel has the required deformable-convolution op on
        # the build PC; fresh installs get it from the corrected models recipe.
        candidates = ([Path(override)] if override else
                      [music_env / 'Scripts' / 'python.exe', models_env / 'Scripts' / 'python.exe'])
        self.proc = None
        error = None
        for python in candidates:
            if not python.is_file():
                continue
            env = dict(os.environ)
            if python == music_env / 'Scripts' / 'python.exe':
                env['LETITEDIT_BIREFNET_PACKAGES'] = str(models_env / 'Lib' / 'site-packages')
            log = root / 'cache' / 'portrait-mattes' / 'worker.log'
            log.parent.mkdir(parents=True, exist_ok=True)
            stderr = open(log, 'ab')
            stderr.write(f'\nworker candidate {python}\n'.encode())
            stderr.flush()
            proc = subprocess.Popen([str(python), '-u', str(Path(__file__).with_name('birefnet_worker.py')),
                                     str(model)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=stderr, env=env,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            stderr.close()
            try:
                if _greeting(proc) != b'READY':
                    raise RuntimeError('BiRefNet worker did not start')
                self.proc = proc
                break
            except Exception as ex:
                error = f'{python}: {ex}; see {log}'
                _stop_tree(proc)
        if self.proc is None:
            raise RuntimeError(f'CUDA BiRefNet unavailable: {error}')

    def __call__(self, frame):
        frame = np.ascontiguousarray(frame, dtype=np.uint8)
        height, width = frame.shape[:2]
        self.proc.stdin.write(struct.pack('<II', width, height) + frame.tobytes())
        self.proc.stdin.flush()
        outcome = {}
        def read():
            try:
                n = struct.unpack('<I', _read_exact(self.proc.stdout, 4))[0]
                outcome['size'] = n
                if n != width * height * 2:
                    raise RuntimeError('BiRefNet worker returned an invalid matte')
                outcome['value'] = _read_exact(self.proc.stdout, n)
            except Exception as ex:
                outcome['error'] = ex
        thread = threading.Thread(target=read, daemon=True)
        thread.start()
        thread.join(30)
        if thread.is_alive():
            _stop_tree(self.proc)
            raise TimeoutError('BiRefNet worker took over 30 seconds for one frame')
        if 'error' in outcome:
            raise outcome['error']
        n = outcome['size']
        if n != width * height * 2:
            raise RuntimeError('BiRefNet worker returned an invalid matte')
        return np.frombuffer(outcome['value'], np.float16).reshape(height, width).astype(np.float32)

    def send(self, frame):
        """Hand a frame over without waiting for its matte; receive() gives the mattes back in the same order."""
        frame = np.ascontiguousarray(frame, dtype=np.uint8)
        height, width = frame.shape[:2]
        self.proc.stdin.write(struct.pack('<II', width, height) + frame.tobytes())
        self.proc.stdin.flush()

    def receive(self, frame):
        """The matte of the frame sent longest ago; `frame` is that frame (for its size). The caller guards against a
        worker that stops answering (stop() ends the wait)."""
        height, width = frame.shape[:2]
        n = struct.unpack('<I', _read_exact(self.proc.stdout, 4))[0]
        if n != width * height * 2:
            raise RuntimeError('BiRefNet worker returned an invalid matte')
        return np.frombuffer(_read_exact(self.proc.stdout, n), np.float16).reshape(height, width).astype(np.float32)

    def stop(self):
        if self.proc is not None:
            _stop_tree(self.proc)

    def close(self):
        if self.proc is not None:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                _stop_tree(self.proc)
            self.proc = None

    def __del__(self):
        self.close()
