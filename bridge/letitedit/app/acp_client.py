"""A small client for the Agent Client Protocol, the way letitedit reaches a connector AI (ai_list.json, protocol "acp").

Newline-delimited JSON-RPC over the connector's stdin and stdout. It says who it is (clientInfo.name = "letitedit"), and
never reads a sign-in file or sends a made-up identity. Nothing here names any one AI: an AI's quirks live in its adapter
(Adapter below is the default; ai_antigravity.py is Google's).

Each start gets its own temp folder, emptied when it ends, because a connector can unpack a lot there. The whole process tree
ends with this process, even if this process is killed (a Windows job object).
"""
import base64
import ctypes
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

CLIENT_NAME = 'letitedit'
PROTOCOL_VERSION = 1
SECRET = re.compile(r'(token|secret|password|authorization|cookie)', re.I)
QUERY = re.compile(r'(https?://[^\s"\'<>?]+)\?[^\s"\'<>]*')


class AcpError(RuntimeError):
    """The connector answered a request with an error."""

    def __init__(self, method, error):
        self.method, self.error = method, error if isinstance(error, dict) else {'message': str(error)}
        super().__init__(f"{method}: {self.error.get('message', error)}")


class Gone(RuntimeError):
    """The connector's process ended."""


def _kill_on_close_job():
    """A job object that ends everything in it when this process goes, however it goes. None when it can't be made."""
    if os.name != 'nt':
        return None

    class Basic(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                    ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]

    class Io(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ('r', 'w', 'o', 'rb', 'wb', 'ob')]

    class Extended(ctypes.Structure):
        _fields_ = [('Basic', Basic), ('Io', Io), ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                    ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = Extended()
    info.Basic.LimitFlags = 0x2000      # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):   # JobObjectExtendedLimitInformation
        return None
    return k32, job


class Adapter:
    """What differs between one connector AI and the next. This default fits a program that follows the protocol plainly."""

    def __init__(self, entry, settings=None):
        self.entry, self.settings = entry, settings or {}

    # --- starting it
    def env(self, base, profile, temp):
        """The connector's environment. `base` is a copy of this process's."""
        base.update({'TEMP': str(temp), 'TMP': str(temp), 'PYTHONUNBUFFERED': '1'})
        if self.entry.get('home_var'):
            base[self.entry['home_var']] = str(profile)
        return base

    def validate_initialize(self, reply):
        """Words saying what's wrong with the connector's answer to initialize, or None."""
        return None

    def session_meta(self, rules, disabled=()):
        """The connector's own extras for session/new and session/resume. None means the rules go in the first prompt."""
        return None

    def install_skills(self, profile):
        """Puts the letitedit skills where this AI reads them. Returns the folder or None."""
        return None

    # --- reading it
    def picture_from(self, update):
        """(path, base64 data) of a picture a tool call made, from the call's own record: the path in rawOutput, or the bytes
        inline. Never the agent's words."""
        raw = update.get('rawOutput')
        path = raw.get('imagePath') if isinstance(raw, dict) else None
        data = None
        for block in update.get('content') or []:
            inner = block.get('content') if isinstance(block, dict) else None
            if isinstance(inner, dict) and inner.get('type') == 'image' and inner.get('data'):
                data = inner['data']
        return path, data

    def tool_name(self, update):
        """What a tool call is called: letitedit's tools as the panel knows them, others by their title."""
        meta = (update.get('_meta') or {}).get('mcp') or {}
        if meta.get('tool'):
            return f"mcp__{meta.get('server', 'tool')}__{meta['tool']}"
        return str(update.get('title') or update.get('kind') or 'a step')

    def tool_input(self, update):
        raw = update.get('rawInput')
        if isinstance(raw, dict) and isinstance(raw.get('arguments'), dict):
            return raw['arguments']
        return raw if isinstance(raw, dict) else {}

    def turn_failure(self, text, stop_reason, stderr):
        """A turn that "finished" but failed: None, or {'kind': 'limit'|'signin'|'failed', 'words': ...}. Connectors report
        some failures as a normal end of turn."""
        return None

    def image_limit(self, text, stderr):
        """Words when a turn says the picture allowance has run out, while chat still works; else None."""
        return None

    def signin_refused(self, error):
        """A sign-in refused: {'state', 'message', ...} in words for a person."""
        return {'state': 'failed', 'message': str(error.get('message') or error)}


class Connector:
    """One running connector process."""

    def __init__(self, exe, cwd, env, on_update=None, on_permission=None, log_path=None, temp=None):
        self.on_update, self.on_permission = on_update, on_permission
        self.temp = Path(temp) if temp else None
        self.log = open(log_path, 'a', encoding='utf-8') if log_path else None
        self.stderr = []
        self.reply = None
        self._next, self._pending, self._lock = 1, {}, threading.Lock()
        self.closed = threading.Event()
        command = [sys.executable, exe] if str(exe).lower().endswith('.py') else [str(exe)]
        self._job = _kill_on_close_job()
        os.makedirs(cwd, exist_ok=True)
        self.process = subprocess.Popen(command, cwd=str(cwd), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
        if self._job:
            self._job[0].AssignProcessToJobObject(self._job[1], int(self.process._handle))
        threading.Thread(target=self._read_out, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()

    def _note(self, kind, text):
        if self.log:
            try:
                self.log.write(f'{time.strftime("%H:%M:%S")} {kind} {QUERY.sub(r"\1?...", str(text))[:2000]}\n')
                self.log.flush()
            except (OSError, ValueError):
                pass

    def _read_out(self):
        for raw in iter(self.process.stdout.readline, b''):
            line = raw.decode('utf-8', 'replace').strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if not isinstance(msg, dict):
                    raise ValueError
            except ValueError:
                self._note('stray', line)
                continue
            self._dispatch(msg)
        self.closed.set()
        with self._lock:
            pending = list(self._pending.values())
        for box in pending:
            box.put(None)

    def _read_err(self):
        for raw in iter(self.process.stderr.readline, b''):
            line = raw.decode('utf-8', 'replace').rstrip()
            self.stderr = (self.stderr + [line])[-300:]
            self._note('err', line)

    def _dispatch(self, msg):
        if 'method' in msg and 'id' in msg:
            threading.Thread(target=self._their_request, args=(msg,), daemon=True).start()
        elif 'method' in msg:
            if msg['method'] == 'session/update' and self.on_update:
                self.on_update(msg.get('params') or {})
        elif 'id' in msg:
            box = self._pending.get(msg['id'])
            if box:
                box.put(msg)

    def _their_request(self, msg):
        if msg['method'] == 'session/request_permission':
            params = msg.get('params') or {}
            choice = self.on_permission(params) if self.on_permission else None
            outcome = {'outcome': 'selected', 'optionId': choice} if choice else {'outcome': 'cancelled'}
            self._send({'jsonrpc': '2.0', 'id': msg['id'], 'result': {'outcome': outcome}})
        else:       # files and terminals: initialize says we offer neither
            self._send({'jsonrpc': '2.0', 'id': msg['id'], 'error': {'code': -32601, 'message': 'not supported by letitedit'}})

    def _send(self, obj):
        data = (json.dumps(obj) + '\n').encode('utf-8')
        with self._lock:
            try:
                self.process.stdin.write(data)
                self.process.stdin.flush()
            except (OSError, ValueError) as exc:
                raise Gone(str(exc)) from exc

    def request(self, method, params=None, timeout=120):
        with self._lock:
            rid, self._next = self._next, self._next + 1
            box = queue.Queue()
            self._pending[rid] = box
        self._send({'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params or {}})
        try:
            msg = box.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f'{method}: no answer in {timeout} s') from None
        finally:
            self._pending.pop(rid, None)
        if msg is None:
            raise Gone(f'the connector ended during {method}')
        if 'error' in msg:
            raise AcpError(method, msg['error'])
        return msg.get('result') or {}

    def notify(self, method, params=None):
        self._send({'jsonrpc': '2.0', 'method': method, 'params': params or {}})

    # --- the protocol's steps
    def initialize(self, version='1'):
        self.reply = self.request('initialize', {
            'protocolVersion': PROTOCOL_VERSION,
            'clientCapabilities': {'fs': {'readTextFile': False, 'writeTextFile': False}, 'terminal': False},
            'clientInfo': {'name': CLIENT_NAME, 'title': 'letitedit', 'version': version}}, timeout=180)
        return self.reply

    def can_resume(self):
        caps = (self.reply or {}).get('agentCapabilities') or {}
        return 'resume' in (caps.get('sessionCapabilities') or {}), bool(caps.get('loadSession'))

    def end(self):
        """Ends the whole tree and empties this start's temp folder."""
        try:
            self.process.stdin.close()
        except (OSError, ValueError):
            pass
        if self.process.poll() is None:
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(self.process.pid)], capture_output=True)
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
        if self.log:
            self.log.close()
            self.log = None
        if self.temp:
            remove_temp(self.temp)


def remove_temp(folder):
    """Empties a connector's temp folder; a file still in use stays until the next start's clean-up."""
    shutil.rmtree(folder, ignore_errors=True)


def clean_old_temps(root):
    """Temp folders of starts whose process is gone (a window closed in the middle, a power cut)."""
    root = Path(root)
    if not root.is_dir():
        return
    for folder in root.iterdir():
        pid = folder.name.split('-')[0]
        if not (folder.is_dir() and pid.isdigit()):
            continue
        run = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'], capture_output=True, text=True, errors='replace')
        if pid not in (run.stdout or ''):
            remove_temp(folder)


def image_block(path):
    """A picture as a prompt block."""
    data = Path(path).read_bytes()
    kind = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}.get(Path(path).suffix.lower(), 'image/png')
    return {'type': 'image', 'mimeType': kind, 'data': base64.b64encode(data).decode('ascii')}
