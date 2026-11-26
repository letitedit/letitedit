"""Local alias for Learn's reference measurements."""
import importlib
import sys

sys.modules[__name__] = importlib.import_module('letitedit.looks.learn_measure')
