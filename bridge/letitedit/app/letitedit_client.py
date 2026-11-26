"""Client for the bridge inside letitedit (the custom Shotcut build).

The bridge is a Windows named pipe (\\\\.\\pipe\\letitedit-bridge) that speaks
newline-delimited JSON: {"id", "method", "params"} -> {"id", "ok", "result"|"error"}.
"""
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from collections import deque
import itertools
import json
from pathlib import Path
import os
import subprocess
import threading
import time
import letitedit.app.letitedit_instances as instances

if os.name == 'nt':
    import _winapi

_cancelled_io = deque()


def _reap_cancelled_io():
    """Keep cancelled native buffers alive until completion, without waiting for cleanup."""
    for unused in range(min(len(_cancelled_io), 32)):
        try:
            handle, operation = _cancelled_io.popleft()
        except IndexError:
            break
        if _winapi.WaitForSingleObject(operation.event, 0) != _winapi.WAIT_OBJECT_0:
            _cancelled_io.append((handle, operation))
            continue
        try:
            operation.GetOverlappedResult(False)
        except OSError:
            pass
        _winapi.CloseHandle(handle)

PIPE_PATH = r"\\.\pipe\letitedit-bridge"
SHOTCUT_EXE = (_SAI_ROOT + '\\app\\letitedit.exe')
SHOTCUT_APPDATA = (_SAI_ROOT + '\\appdata')


class BridgeError(Exception):
    """The bridge answered with ok=false."""


class BridgeUnavailable(Exception):
    """The window's bridge could not be reached or did not answer in time."""


class ShotcutBridge:
    def __init__(self, timeout=15.0):
        self.timeout = timeout
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._pipe = None
        self._buffer = bytearray()

    def connect(self):
        if self._pipe is not None:
            return self
        if os.name != 'nt':
            raise BridgeUnavailable('The letitedit window bridge requires Windows.')
        _reap_cancelled_io()
        try:
            self._pipe = _winapi.CreateFile('\\\\.\\pipe\\' + instances.pipe_name(),
                                           _winapi.GENERIC_READ | _winapi.GENERIC_WRITE,
                                           0, _winapi.NULL, _winapi.OPEN_EXISTING,
                                           _winapi.FILE_FLAG_OVERLAPPED, _winapi.NULL)
        except FileNotFoundError as exc:
            raise BridgeUnavailable(
                f"The custom letitedit window '{instances.current()}' is not running. Start it with "
                "launch_shotcut() or the 'letitedit' desktop shortcut."
            ) from exc
        except OSError as exc:
            raise BridgeUnavailable(f"Could not connect to letitedit window '{instances.current()}': {exc}") from exc
        return self

    def close(self):
        if self._pipe is not None:
            _winapi.CloseHandle(self._pipe)
            self._pipe = None
        self._buffer.clear()
        if os.name == 'nt':
            _reap_cancelled_io()

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    def _timeout(self, method, phase):
        return BridgeUnavailable(
            f"letitedit window '{instances.current()}' timed out waiting for {phase} "
            f"for '{method}' (limit {self.timeout}s). No further request will be sent automatically. "
            "A sent change may still finish in the window; "
            "read its state before retrying a change.")

    def _remaining(self, deadline, method, phase):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise self._timeout(method, phase)
        return remaining

    def _io(self, data, deadline, method, phase):
        remaining = self._remaining(deadline, method, phase)
        if data is None:
            operation, error = _winapi.ReadFile(self._pipe, 65536, overlapped=True)
        else:
            operation, error = _winapi.WriteFile(self._pipe, data, overlapped=True)
        try:
            if error == _winapi.ERROR_IO_PENDING:
                milliseconds = max(1, min(0xfffffffe, int(remaining * 1000)))
                if _winapi.WaitForSingleObject(operation.event, milliseconds) != _winapi.WAIT_OBJECT_0:
                    raise self._timeout(method, phase)
            transferred, error = operation.GetOverlappedResult(False)
            if error not in (0, _winapi.ERROR_MORE_DATA):
                raise OSError(error, 'bridge I/O did not complete')
            return operation.getbuffer() if data is None else transferred
        except BaseException:
            handle, self._pipe = self._pipe, None
            _cancelled_io.append((handle, operation))
            try:
                operation.cancel()
            except OSError:
                pass
            self._buffer.clear()
            _reap_cancelled_io()
            raise

    def _read_line(self, deadline, method):
        while b'\n' not in self._buffer:
            chunk = self._io(None, deadline, method, 'a complete reply')
            if not chunk:
                raise BridgeUnavailable(f"letitedit window '{instances.current()}' closed the bridge connection.")
            self._buffer.extend(chunk)
        line, _, rest = self._buffer.partition(b'\n')
        self._buffer = bytearray(rest)
        return bytes(line)

    def _request(self, line, deadline, method):
        remaining = self._remaining(deadline, method, 'the bridge request lock')
        if not self._lock.acquire(timeout=remaining):
            raise self._timeout(method, 'the bridge request lock')
        try:
            self._remaining(deadline, method, 'the bridge connection')
            self.connect()
            written = self._io(line, deadline, method, 'the request to be sent')
            if written != len(line):
                raise BridgeUnavailable(f"letitedit window '{instances.current()}' accepted only part of '{method}'.")
            return json.loads(self._read_line(deadline, method))
        except OSError as exc:
            self.close()
            raise BridgeUnavailable(f"letitedit window '{instances.current()}' lost the bridge during '{method}': {exc}") from exc
        except BaseException:
            self.close()
            raise
        finally:
            self._lock.release()

    def raw(self, line: bytes) -> dict:
        """Send raw bytes (for testing error handling) and return the parsed reply."""
        return self._request(line, time.monotonic() + self.timeout, 'raw request')

    def call(self, method, params=None):
        # Shotcut refuses changes while a project is opening (its old timeline is being replaced): wait for it.
        for attempt in range(80):
            try:
                return self._call(method, params)
            except BridgeError as exc:
                if 'still opening' not in str(exc) or attempt == 79:
                    raise
                time.sleep(0.25)

    def _call(self, method, params=None, *, _deadline=None):
        deadline = _deadline if _deadline is not None else time.monotonic() + self.timeout
        if method not in instances.READ_METHODS:
            instances.claim_instance()
            target=(params or {}).get('path') if method in ('open','save') else None
            if target and str(target).lower().endswith('.mlt'):
                instances.claim_project(target)
            if method != 'open':
                state=self._call('state', _deadline=deadline)
                if state.get('project'):instances.claim_project(state['project'])
        request_id = next(self._ids)
        request = {"id": request_id, "method": method, "params": params or {}}
        reply = self._request((json.dumps(request) + "\n").encode("utf-8"), deadline, method)
        if reply.get("id") != request_id:
            raise BridgeError(f"Mismatched reply id: {reply}")
        if not reply.get("ok"):
            raise BridgeError(reply.get("error", "unknown error"))
        return reply.get("result")


def is_running():
    try:
        with ShotcutBridge(timeout=5) as bridge:
            bridge.call("ping")
        return True
    except (BridgeUnavailable, BridgeError, OSError):
        return False


def launch(project=None, wait=60.0, quiet=False):
    """Start letitedit (if needed) and wait for the bridge to answer. quiet: the new window must not take the keyboard
    focus or come up over the app in front (an AI opened it, nobody clicked)."""
    instances.claim_instance()
    if project and str(project).lower().endswith('.mlt'):instances.claim_project(project)
    if is_running():
        return {"already_running": True, "instance_id":instances.current()}
    appdata = SHOTCUT_APPDATA if instances.current()=='main' else str(instances.ROOT/instances.current()/'appdata')
    os.makedirs(appdata, exist_ok=True)
    executable=SHOTCUT_EXE
    pointer=Path((_SAI_ROOT + '\\app\\ai-assist-executable.txt'))
    if pointer.exists():
        candidate=Path(pointer.read_text(encoding="utf-8-sig").strip()).resolve()
        if candidate.parent==Path((_SAI_ROOT + '\\app')).resolve() and candidate.is_file():executable=str(candidate)
    args = [executable, "--noupgrade", "--appdata", appdata]
    if project:
        args.append(project)
    # Editor is not an AI owner: once clients/jobs exit, another conversation can take over.
    env=instances.worker_env();env.pop('LETITEDIT_OWNER',None);env.pop('LETITEDIT_TOOL_SERVER_PID',None)
    if quiet:env['LETITEDIT_OPEN_QUIETLY']='1'
    # Never in a job it would die with (a supervised job, render_lock.py run's command): breakaway, else the broker.
    import letitedit.core.render_lock as render_lock
    render_lock.start_independent(args, env=env, creationflags=subprocess.DETACHED_PROCESS)
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(1)
        if is_running():
            break
    else:
        raise BridgeUnavailable(f"letitedit started but the bridge did not answer within {wait}s.")
    if project:
        # The bridge comes up before Shotcut finishes opening the file given on the command line.
        wanted = os.path.normcase(os.path.abspath(project))
        while time.time() < deadline:
            try:
                with ShotcutBridge(timeout=5) as bridge:
                    state = bridge.call("state")
                if os.path.normcase(os.path.abspath(state.get("project") or "")) == wanted:
                    return {"already_running": False, "started": True, "project": state["project"]}
                if state.get("dialog"):
                    # e.g. "recover autosave?" -- the caller must answer it (dialog_button).
                    return {"already_running": False, "started": True,
                            "waiting_on_dialog": state["dialog"]}
            except (BridgeUnavailable, BridgeError):
                pass
            time.sleep(0.5)
        raise BridgeUnavailable(f"letitedit started but did not finish opening {project} within {wait}s.")
    return {"already_running": False, "started": True, "instance_id":instances.current()}
