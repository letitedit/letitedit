"""Microsoft's Visual C++ runtime (msvcp140.dll and the files that go with it) on a PC whose Windows doesn't have it.

Several packages the tools load need it (onnxruntime, ctranslate2 for speech-to-text, espeak-ng, torch). Most PCs
have it from some other program; a clean Windows doesn't, and then those packages fail with "DLL load failed".
The installer carries Microsoft's own redistributable installer (setup\\vc_redist.x64.exe, signed by Microsoft) and
runs it only when Windows lacks the runtime or has one older than the packages need. It installs into Windows, so
Windows asks once for an administrator's OK (a person without admin rights is asked for an administrator's
password; if nobody gives it, the tools' setup stops and says so).

Standard library only. As a script (setup runs it before any package is installed):
    python -I vc_runtime.py --check            one JSON line: {"needed": bool, "have": "14.xx.xxxxx" or null}
    python -I vc_runtime.py --ensure <app>     runs <app>\\setup\\vc_redist.x64.exe when needed; one JSON line, exit 1
                                               when the runtime still isn't there afterwards
"""
import json
import os
import sys

# what the tools' packages ask Windows for (read from their import tables on a clean PC, 18 Nov 2026)
NEEDED = ('msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'concrt140.dll')
# packages built with Visual Studio 2022 17.10 or later crash on an older msvcp140.dll (Microsoft's STL changed its
# mutex then), so an older runtime counts as missing
MINIMUM = (14, 40)
REDIST = ('setup', 'vc_redist.x64.exe')
ARGS = '/install /quiet /norestart'
CANCELLED = 1223                  # ERROR_CANCELLED: the admin prompt was declined
BLOCKED = -1260                   # Windows refused to ask at all (ERROR_ACCESS_DISABLED_BY_POLICY 1260, ACCESS_DENIED 5):
                                  # this account's elevation requests are refused automatically
OK_CODES = (0, 1638, 3010)        # done; a newer one is already there; done, a restart finishes it
# Windows' prompt waits for an answer; with no desktop to show it on (setup started as a background job) it never comes
PROMPT_WAIT_S = 900


def _system32():
    return os.path.join(os.environ.get('SystemRoot') or os.environ.get('WINDIR') or r'C:\Windows', 'System32')


def installed_version():
    """The version Windows records for the x64 runtime ('14.52.37029'), or None."""
    try:
        import winreg
        flags = winreg.KEY_READ | getattr(winreg, 'KEY_WOW64_64KEY', 0)
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64', 0, flags) as k:
            if not winreg.QueryValueEx(k, 'Installed')[0]:
                return None
            return '.'.join(str(winreg.QueryValueEx(k, n)[0]) for n in ('Major', 'Minor', 'Bld'))
    except (OSError, ImportError):
        return None


def windows_has():
    """True when Windows' own folder has every file the packages ask for, from a runtime new enough for them."""
    if not all(os.path.isfile(os.path.join(_system32(), n)) for n in NEEDED):
        return False
    have = installed_version()
    if have is None:                # the files without Microsoft's record (an unusual install): trust the files
        return True
    return tuple(int(x) for x in have.split('.')[:2]) >= MINIMUM


def _run_elevated(exe, args):
    """Run exe with Windows' 'run as administrator' (one prompt unless this process is already elevated); wait;
    its exit code, or CANCELLED when the prompt was declined."""
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG), ('hwnd', wintypes.HWND),
                    ('lpVerb', wintypes.LPCWSTR), ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR),
                    ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE),
                    ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
                    ('dwHotKey', wintypes.DWORD), ('hIconOrMonitor', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)]

    shell32 = ctypes.WinDLL('shell32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    # NOCLOSEPROCESS, NOASYNC, FLAG_NO_UI: without NO_UI a refused elevation ("Your system administrator has blocked
    # this program") opens Windows' own error box and the call waits for its OK, so setup sits behind it
    info = SHELLEXECUTEINFOW(cbSize=ctypes.sizeof(SHELLEXECUTEINFOW), fMask=0x00000040 | 0x00000100 | 0x00000400,
                             lpVerb='runas', lpFile=exe, lpParameters=args, nShow=0)
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.get_last_error()
        return CANCELLED if err == CANCELLED else BLOCKED if err in (5, 1260) else -err
    try:
        kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value
    finally:
        kernel32.CloseHandle(info.hProcess)


def _within(run, exe, args, seconds):
    """run(exe, args) on a helper thread; its result, or None when it hasn't returned within seconds."""
    import threading
    box = []
    worker = threading.Thread(target=lambda: box.append(run(exe, args)), daemon=True)
    worker.start()
    worker.join(seconds)
    return box[0] if box else None


def ensure(app_dir, log=None, run=None):
    """Make sure Windows has the runtime, running the installer's copy of Microsoft's redistributable when it
    doesn't. Returns what happened; raises RuntimeError (in plain words) when the runtime still isn't there."""
    say = log or (lambda text: None)
    if windows_has():
        return {'needed': False, 'have': installed_version()}
    redist = os.path.join(app_dir, *REDIST)
    if not os.path.isfile(redist):
        raise RuntimeError(f"Windows lacks Microsoft's C++ runtime and {redist} is missing: repair or reinstall letitedit")
    say("Windows doesn't have Microsoft's C++ runtime (or has an older one); installing it. "
        "Windows asks once for an administrator's OK.")
    code = _within(run or _run_elevated, redist, ARGS, PROMPT_WAIT_S)
    if code is None:
        raise RuntimeError(f"Windows' administrator prompt for Microsoft's C++ runtime got no answer within "
                           f"{PROMPT_WAIT_S // 60} minutes (setup may be running where no prompt can show). Someone with "
                           f"admin rights can run {redist} once, then Repair letitedit's Python tools.")
    if code == CANCELLED:
        raise RuntimeError("Windows' administrator prompt for Microsoft's C++ runtime was declined. Someone with "
                           f"admin rights can run {redist} once, then Repair letitedit's Python tools.")
    if code == BLOCKED:
        raise RuntimeError("Windows doesn't let this account install Microsoft's C++ runtime (its requests to run as "
                           f"administrator are refused). Someone with admin rights can run {redist} once, then "
                           "Repair letitedit's Python tools.")
    if code not in OK_CODES or not windows_has():
        raise RuntimeError(f"Microsoft's C++ runtime installer ended with code {code} and the runtime isn't there "
                           f"yet (see %TEMP%\\dd_vcredist_amd64_*.log)")
    return {'needed': True, 'installed': installed_version(), 'exit': code, 'restart': code == 3010}


if __name__ == '__main__':
    if sys.argv[1:] == ['--check']:
        print(json.dumps({'needed': not windows_has(), 'have': installed_version()}))
        sys.exit(0)
    if len(sys.argv) != 3 or sys.argv[1] != '--ensure':
        raise SystemExit('usage: python -I vc_runtime.py --check | --ensure <app folder>')
    try:
        print(json.dumps(ensure(sys.argv[2], log=lambda t: print(t, file=sys.stderr))))
    except Exception as e:      # setup reads the exit code and this line
        print(json.dumps({'needed': True, 'error': str(e)}))
        sys.exit(1)
