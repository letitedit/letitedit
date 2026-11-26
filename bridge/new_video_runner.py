"""New video's first cut on the session runner, for the editor's chat (T331 P11; the code: letitedit/studio/first_cut.py).
Not a tool and not part of the tools' contract.

    python new_video_runner.py      stdin: one line of JSON {"folder", "request", "progress_run"?, "engine"?},
                                    then "stop" (or stdin closed) to stop
    stdout: one JSON event a line: fallback {reason} | started {project, phases} | progress {message, phase?} |
            done {project, export, status} | stopped {code, message, phase?}

A fallback starts nothing: the editor then sends the request to its AI in the window, as before.
"""
import io
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import letitedit.core.quiet_subprocess  # noqa: E402,F401  (no console windows)
from letitedit.studio import first_cut  # noqa: E402

if __name__ == '__main__':
    stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8-sig', errors='replace')
    sys.exit(first_cut.main(stdin, sys.stdout))
