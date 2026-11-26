"""guide_song: the old name of letitedit.sound.guide_song, its real home (one module under both names)."""
import importlib
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
if all(os.path.normcase(os.path.abspath(p or os.curdir)) != os.path.normcase(_here) for p in sys.path):
    sys.path.append(_here)  # python -I leaves this folder off the path; last, so it shadows nothing
sys.modules[__name__] = importlib.import_module('letitedit.sound.guide_song')
