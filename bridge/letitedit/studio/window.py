"""A letitedit window of a Studio job's own, never the person's (CONTRACT.md section 4).

A making job runs New video's own path: the same dialog, stages, skills, review rounds and checks the person gets, in
an editor window that only this job uses:
- on a private Windows desktop of its own, so nothing it shows can take the person's keyboard focus, show on their
  screen or taskbar, or move the cursor (every program it starts lives there too);
- as its own instance (`studio-<hash of the job id>`), with its own appdata, chat settings (a copy of the person's,
  with the job's `ai` applied), chat history, progress feed and Learn folder, so the person's window, chat and New
  video card never see it;
- its renders wait in the PC lock's line in the job's lane (LETITEDIT_LOCK_PRIORITY);
- its projects are saved in the job folder (LETITEDIT_PROJECTS_FOLDER), never beside the footage.

The window is driven through its bridge pipe (qa_widget, qa_mouse, trigger, chat_state), which needs
LETITEDIT_QA=1 in its environment. close() ends it and everything it started.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import letitedit.core.paths as paths

GENERIC_ALL = 0x10000000
STARTF_USESHOWWINDOW = 1
CREATE_UNICODE_ENVIRONMENT = 0x400
CREATE_NO_WINDOW = 0x08000000
CREATE_SUSPENDED = 0x00000004
BELOW_NORMAL = 0x4000
EXE_ENV = 'LETITEDIT_STUDIO_EXE'


def install_root():
    """The install the window runs from (its tools, models, caches and Looks): LETITEDIT_ROOT, else this code's."""
    return Path(os.path.normpath(os.environ.get('LETITEDIT_ROOT') or paths.ROOT_TEXT))


def tool_jobs_root():
    """Where the AI's own tools queue their background jobs (a voice fix, a long export) in a Studio job: the
    install's ordinary jobs folder, never the Studio's queue. A Studio job's process has LETITEDIT_JOBS set to the
    Studio's queue (core.jobs gives each job's process its own queue), whose one worker is busy with that very Studio
    job, so a tool job queued there could only start once the Studio job had ended (T331 P12: a voice fix waited 12
    minutes; T305's preview applied its voice fix after the preview had finished)."""
    return str(install_root() / 'jobs')


def editor_exe():
    """The editor a Studio window runs: LETITEDIT_STUDIO_EXE, else the install's promoted build."""
    if os.environ.get(EXE_ENV):
        return Path(os.environ[EXE_ENV])
    app = install_root() / 'app'
    return app / (app / 'ai-assist-executable.txt').read_text(encoding='utf-8').strip()


def instance_for(job_id):
    """The editor starts its bridge only for an instance name of lower-case letters, digits, - and _."""
    return 'studio-' + hashlib.sha1(str(job_id).encode('utf-8')).hexdigest()[:12]


if os.name == 'nt':
    import ctypes.wintypes as wt
    _u32, _k32 = ctypes.windll.user32, ctypes.windll.kernel32
    _u32.CreateDesktopW.restype = ctypes.c_void_p
    _u32.CreateDesktopW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_ulong,
                                    ctypes.c_ulong, ctypes.c_void_p]
    _u32.CloseDesktop.argtypes = [ctypes.c_void_p]
    _k32.CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wt.BOOL, wt.DWORD,
                                    ctypes.c_void_p, wt.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p]
    _k32.CloseHandle.argtypes = [wt.HANDLE]

    class _STARTUPINFOW(ctypes.Structure):
        _fields_ = [('cb', wt.DWORD), ('lpReserved', wt.LPWSTR), ('lpDesktop', wt.LPWSTR), ('lpTitle', wt.LPWSTR),
                    ('dwX', wt.DWORD), ('dwY', wt.DWORD), ('dwXSize', wt.DWORD), ('dwYSize', wt.DWORD),
                    ('dwXCountChars', wt.DWORD), ('dwYCountChars', wt.DWORD), ('dwFillAttribute', wt.DWORD),
                    ('dwFlags', wt.DWORD), ('wShowWindow', wt.WORD), ('cbReserved2', wt.WORD),
                    ('lpReserved2', ctypes.c_void_p), ('hStdInput', wt.HANDLE), ('hStdOutput', wt.HANDLE),
                    ('hStdError', wt.HANDLE)]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [('hProcess', wt.HANDLE), ('hThread', wt.HANDLE), ('dwProcessId', wt.DWORD),
                    ('dwThreadId', wt.DWORD)]


def _spawn_on_desktop(desktop, args, env, cwd):
    si = _STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.lpDesktop = 'WinSta0' + chr(92) + desktop
    si.dwFlags = STARTF_USESHOWWINDOW
    pi = _PROCESS_INFORMATION()
    block = ctypes.create_unicode_buffer('\0'.join(f'{k}={v}' for k, v in env.items()) + '\0\0')
    ok = _k32.CreateProcessW(None, ctypes.create_unicode_buffer(subprocess.list2cmdline([str(a) for a in args])),
                             None, None, False,
                             BELOW_NORMAL | CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW | CREATE_SUSPENDED, block,
                             str(cwd), ctypes.byref(si), ctypes.byref(pi))
    if not ok:
        raise OSError(f'CreateProcess failed: {_k32.GetLastError()}')
    try:
        # Born suspended, tied to this process's owner job (kill-on-close, breakaway allowed so the editor's own
        # deliberately independent workers still start), then let go: it never runs a single instruction untied, and
        # it ends with its owner however the owner ends. render_lock ends it when it can't be tied.
        import letitedit.core.render_lock as render_lock
        render_lock.tie_process(pi.hProcess, strict=False)
        render_lock.resume_process(pi.hProcess)
    finally:
        _k32.CloseHandle(pi.hThread)
        _k32.CloseHandle(pi.hProcess)
    return int(pi.dwProcessId)


def _tree(pid):
    """[(pid, creation time)] of a process and everything under it, while it runs (CIM's CreationDate, so a process id
    Windows reuses later is never mistaken for one of these)."""
    if not pid:
        return []
    ps = (f"$root = {int(pid)}; $all = Get-CimInstance Win32_Process; $out = @(); $todo = @($root); "
          "while ($todo.Count) { $p = $todo[0]; $todo = @($todo | Select-Object -Skip 1); "
          "$me = $all | Where-Object { $_.ProcessId -eq $p }; if ($me) { $out += ('{0} {1}' -f $me.ProcessId, "
          "$me.CreationDate.ToFileTimeUtc()) }; "
          "$kids = $all | Where-Object { $_.ParentProcessId -eq $p -and $_.CreationDate -ge $me.CreationDate }; "
          "foreach ($k in $kids) { $todo += $k.ProcessId } }; $out -join \"`n\"")
    try:
        text = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], capture_output=True,
                              text=True, timeout=60, creationflags=CREATE_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for line in (text or '').splitlines():
        bits = line.split()
        if len(bits) == 2 and bits[0].isdigit():
            out.append((int(bits[0]), bits[1]))
    return out


def _end(tree):
    """End the processes of a snapshot that still run as the same processes (the same creation time)."""
    if not tree:
        return
    wanted = ' '.join(f"'{p}={c}'" for p, c in tree)
    ps = (f"$want = @({wanted.replace(' ', ',')}); foreach ($w in $want) {{ $p, $c = $w.Split('='); "
          "$x = Get-CimInstance Win32_Process -Filter \"ProcessId=$p\"; "
          "if ($x -and [string]$x.CreationDate.ToFileTimeUtc() -eq $c) { Stop-Process -Id $p -Force "
          "-ErrorAction SilentlyContinue } }")
    try:
        subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], capture_output=True, text=True,
                       timeout=90, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        pass


class StudioWindow:
    """One hidden editor window for one Studio job. env: more variables for the window (the preview's stop)."""

    def __init__(self, home, job, job_dir, lane, env=None):
        self.job_id, self.job_dir = job['job_id'], Path(job_dir)
        self.instance = instance_for(self.job_id)
        self.base = Path(home) / 'windows' / self.instance
        self.appdata = self.base / 'appdata'
        self.chat_settings = self.base / 'chat' / 'panel.json'
        self.work_dir = self.base / 'ai'                 # where the AI starts: never under the install (it would
        self.projects = self.job_dir / 'work'            # read the install's own agent instructions)
        self.lane = lane
        self.ai = job.get('ai') or {}
        self.extra_env = dict(env or {})
        self.pid = None
        self.desktop = None
        self.root = install_root()

    # ------------------------------------------------------------------ settings
    def _write_settings(self):
        own = {}
        person = self.root / 'chat' / 'panel.json'
        try:
            own = json.loads(person.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            pass
        own['work_dir'] = str(self.work_dir)
        own['mcp_server'] = str(paths.BRIDGE / 'letitedit_mcp.py')    # the Studio's own tools, the code running it
        # the job's `ai` overrides the person's chat choice for this window only (their own settings are never
        # written); an effort or model without an engine is for the engine they use. No `ai`: theirs, as it is.
        asked = bool(self.ai.get('effort') or self.ai.get('model'))
        engine = self.ai.get('engine') or ((own.get('engine') or 'claude') if asked else None)
        if engine:
            own['engine'] = engine
            if engine == 'claude':
                if self.ai.get('model'):
                    own['model'] = self.ai['model']
                if self.ai.get('effort'):
                    own['effort'] = self.ai['effort']
            elif engine == 'codex':
                if self.ai.get('model'):
                    own['codex_model'] = self.ai['model']
                if self.ai.get('effort'):
                    own['codex_reasoning'] = self.ai['effort']
        own['view_mode'] = own.get('view_mode') or 'bubbles'
        self.chat_settings.parent.mkdir(parents=True, exist_ok=True)
        self.chat_settings.write_text(json.dumps(own, indent=2), encoding='utf-8')
        return own

    def settings(self):
        try:
            return json.loads(self.chat_settings.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            return {}

    def env(self):
        e = {k: v for k, v in os.environ.items()
             if not (k.startswith('CLAUDE') or k.startswith('T3CODE')) or k == 'CLAUDE_CONFIG_DIR'}
        for k in ('LETITEDIT_STUDIO_HOME', 'LETITEDIT_OWNER', 'LETITEDIT_QA_MOCK_AI', 'LETITEDIT_INSTANCE'):
            e.pop(k, None)
        e.update(LETITEDIT_ROOT=str(self.root), LETITEDIT_INSTANCE=self.instance, LETITEDIT_JOBS=tool_jobs_root(),
                 LETITEDIT_CHAT_SETTINGS=str(self.chat_settings), LETITEDIT_QA='1', LETITEDIT_QA_ONSCREEN='1',
                 QSG_RHI_BACKEND='d3d11', LETITEDIT_PROJECTS_FOLDER=str(self.projects),
                 LETITEDIT_PROGRESS_DIR=str(self.base / 'progress'), LETITEDIT_LEARN_JOBS=str(self.base / 'learning'),
                 LETITEDIT_SHARE_URL='off', LETITEDIT_SHARING_DIR=str(self.base / 'sharing'),
                 LETITEDIT_QA_REVIEW_NO_OFFER='1', LETITEDIT_LOCK_PRIORITY=self.lane,
                 WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--disable-features=CalculateNativeWinOcclusion '
                 '--disable-backgrounding-occluded-windows --disable-renderer-backgrounding '
                 '--disable-background-timer-throttling')
        e.update(self.extra_env)
        return e

    # ------------------------------------------------------------------ the window
    def start(self, timeout=180):
        self.close_stale()
        if self.appdata.exists():
            shutil.rmtree(self.appdata, ignore_errors=True)
        for d in (self.appdata, self.work_dir, self.projects, self.base / 'progress', self.base / 'learning'):
            d.mkdir(parents=True, exist_ok=True)
        (self.chat_settings.parent / 'history.json').unlink(missing_ok=True)
        self._write_settings()
        exe = editor_exe()
        if not exe.is_file():
            import letitedit.studio.state as state
            raise state.StudioError('internal', "letitedit's editor was not found, so the job could not run.",
                                    detail=str(exe))
        args = [exe, '--noupgrade', '--appdata', self.appdata]
        if os.name == 'nt':
            self.desktop = f'letitedit-studio-{self.instance}'
            handle = _u32.CreateDesktopW(self.desktop, None, None, 0, GENERIC_ALL, None)
            if not handle:
                raise OSError(f'CreateDesktop failed: {_k32.GetLastError()}')
            self._desktop_handle = handle
            self.pid = _spawn_on_desktop(self.desktop, args, self.env(), self.work_dir)
        else:                                            # pragma: no cover - letitedit's windows are Windows only
            self.pid = subprocess.Popen([str(a) for a in args], env=self.env(), cwd=self.work_dir).pid
        self._record()
        end = time.time() + timeout
        while time.time() < end:
            try:
                self.call('state', timeout=5)
                break
            except Exception:  # noqa: BLE001 - still starting
                time.sleep(1)
        else:
            self.close()
            import letitedit.studio.state as state
            raise state.StudioError('internal', "letitedit's window for this job did not start.",
                                    detail=f'{exe} instance {self.instance}')
        time.sleep(2.5)
        return self

    def _record(self):
        """window.json: the window's pid and its process tree as it is now (refreshed while the job watches it), so a
        later attempt can end exactly these processes."""
        self.tree = _tree(self.pid) or getattr(self, 'tree', [])
        (self.base / 'window.json').write_text(json.dumps({'pid': self.pid, 'job_id': self.job_id,
                                                           'tree': self.tree, 'at': time.time()}), encoding='utf-8')

    def refresh(self):
        if self.pid and self.alive():
            self._record()

    def close_stale(self):
        """A window this job started in an earlier attempt (its process stopped, the window may not have): ended,
        with what it started."""
        known = self.base / 'window.json'
        try:
            tree = [tuple(t) for t in json.loads(known.read_text(encoding='utf-8-sig')).get('tree') or []]
        except (OSError, ValueError):
            tree = []
        _end(tree)
        known.unlink(missing_ok=True)

    def call(self, method, params=None, timeout=None):
        """A call into the window, as the person's own use of the app (instances.app_edit): the Studio drives the
        dialog and opens projects the way a person does, so it never claims the window as an AI session. A claim
        here would refuse every edit of the window's own AI ("belongs to another active AI session")."""
        import letitedit.app.letitedit_instances as instances
        from letitedit.app.letitedit_client import ShotcutBridge
        with instances.scope(self.instance), instances.app_edit():
            with (ShotcutBridge(timeout=timeout) if timeout else ShotcutBridge()) as b:
                return b.call(method, params)

    def alive(self):
        if not self.pid:
            return False
        try:
            import letitedit.core.render_lock as render_lock
            return bool(render_lock.pid_alive(self.pid))
        except Exception:  # noqa: BLE001
            return True

    def widget(self, name, action='state', value=None):
        params = {'name': name, 'action': action}
        if value is not None:
            params['value'] = value
        return self.call('qa_widget', params)

    def peek(self, name):
        try:
            return self.widget(name)
        except Exception as e:  # noqa: BLE001
            return {'missing': str(e)}

    def wait_for(self, fn, timeout=30, every=0.5):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            try:
                last = fn()
                if last:
                    return last
            except Exception as e:  # noqa: BLE001
                last = e
            time.sleep(every)
        return None

    def click(self, name, wait=0.7, timeout=40):
        self.wait_for(lambda: self.widget(name).get('enabled'), timeout, 1)
        out = self.widget(name, 'click')
        time.sleep(wait)
        return out

    def chat_state(self):
        try:
            return self.call('chat_state', timeout=10) or {}
        except Exception:  # noqa: BLE001
            return {}

    def close(self, timeout=25):
        """Exit the window (unsaved changes discarded: the AI saves its own work), then end anything left."""
        self.refresh()
        if self.pid and self.alive():
            def exit_():
                try:
                    self.call('trigger', {'name': 'actionExit'}, timeout=5)
                except Exception:  # noqa: BLE001
                    pass
            threading.Thread(target=exit_, daemon=True).start()
            end = time.time() + timeout
            while time.time() < end and self.alive():
                try:
                    if (self.call('state', timeout=3) or {}).get('modalDialog'):
                        for button in ('No', "Don't Save", 'Discard', 'Close Without Saving'):
                            try:
                                self.call('dialog_button', {'button': button}, timeout=3)
                                break
                            except Exception:  # noqa: BLE001
                                continue
                except Exception:  # noqa: BLE001 - closing
                    pass
                time.sleep(0.5)
        _end(getattr(self, 'tree', []))
        (self.base / 'window.json').unlink(missing_ok=True)
        if getattr(self, '_desktop_handle', None):
            _u32.CloseDesktop(self._desktop_handle)
            self._desktop_handle = None
        self.pid = None
