"""Running a program from the tools.

    run_tool(args, log=None, timeout=7200)
        runs args (each turned into str) with no console window, captures its output as UTF-8 (bad bytes replaced) and
        returns stdout; appends stdout and stderr to log when given; raises RuntimeError naming the program and the end
        of its stderr when it exits non-zero, and subprocess.TimeoutExpired after timeout seconds.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def run_tool(args, log=None, timeout=7200):
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    result = subprocess.run([str(x) for x in args], capture_output=True, encoding='utf-8', errors='replace',
                            timeout=timeout, creationflags=flags)
    if log:
        with Path(log).open('a', encoding='utf-8') as f:
            f.write(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f'{Path(args[0]).name} exited {result.returncode}: {result.stderr[-1600:]}')
    return result.stdout
