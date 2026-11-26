"""render_queue: the old name of letitedit.timeline.render_queue, its real home (one module under both names; run by
path, the real file runs as the script)."""
import importlib
import os
import runpy
import sys

_here = os.path.dirname(os.path.abspath(__file__))
if all(os.path.normcase(os.path.abspath(p or os.curdir)) != os.path.normcase(_here) for p in sys.path):
    sys.path.append(_here)  # python -I leaves this folder off the path; last, so it shadows nothing
if __name__ == '__main__':
    # Independent workers do not inherit the submitter's environment. Set the install
    # root before importing the render module: it resolves melt and ffmpeg at import.
    if len(sys.argv) >= 5 and sys.argv[1] == 'run':
        os.environ['LETITEDIT_ROOT'] = sys.argv[4]
    runpy.run_path(os.path.join(_here, 'letitedit', 'timeline', 'render_queue.py'), run_name='__main__')
else:
    sys.modules[__name__] = importlib.import_module('letitedit.timeline.render_queue')
