"""start_project: the old name of letitedit.app.start_project, its real home (one module under both names; run by
path, the real file runs as the script)."""
import importlib
import os
import runpy
import sys

_here = os.path.dirname(os.path.abspath(__file__))
if all(os.path.normcase(os.path.abspath(p or os.curdir)) != os.path.normcase(_here) for p in sys.path):
    sys.path.append(_here)  # python -I leaves this folder off the path; last, so it shadows nothing
if __name__ == '__main__':
    runpy.run_path(os.path.join(_here, 'letitedit', 'app', 'start_project.py'), run_name='__main__')
else:
    sys.modules[__name__] = importlib.import_module('letitedit.app.start_project')
