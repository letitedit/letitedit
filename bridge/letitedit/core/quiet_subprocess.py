"""Programs this code starts never open a console window, and so never take the keyboard focus (T52).

On Windows a console program started by a program that has no console of its own (the editor, a service, pythonw, a hidden
helper) opens a window of its own, and on a PC whose default terminal is Windows Terminal that window is a real, focused
terminal for a moment: whoever is typing in another window loses what they were typing. CREATE_NO_WINDOW prevents it.

`import quiet_subprocess` (done by the tool server, the Python module, the render lock and the job code) makes every
subprocess.Popen (and so run, call, check_output and asyncio's subprocesses) start with CREATE_NO_WINDOW, unless the caller
chose its own console behaviour (CREATE_NEW_CONSOLE, DETACHED_PROCESS, CREATE_NO_WINDOW already set). Nothing else changes: pipes,
exit codes and output are the same. A program that really wants a console asks for CREATE_NEW_CONSOLE.
"""
import os
import subprocess
import sys

CREATE_NEW_CONSOLE = 0x00000010
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000
_PATCHED = '_letitedit_quiet'


def install():
    if sys.platform != 'win32' or getattr(subprocess.Popen, _PATCHED, False) or os.environ.get('LETITEDIT_VISIBLE_CONSOLES'):
        return
    original = subprocess.Popen.__init__

    def init(self, *args, **kwargs):
        flags = kwargs.get('creationflags', 0) or 0
        if not flags & (CREATE_NEW_CONSOLE | DETACHED_PROCESS | CREATE_NO_WINDOW):
            kwargs['creationflags'] = flags | CREATE_NO_WINDOW
        original(self, *args, **kwargs)

    subprocess.Popen.__init__ = init
    setattr(subprocess.Popen, _PATCHED, True)


install()
