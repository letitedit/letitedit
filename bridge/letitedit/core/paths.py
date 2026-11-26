"""Where letitedit's files are: one answer for every module, whatever folder the module sits in.

Two roots, because the tools have always used both and they differ only when LETITEDIT_ROOT is set (a sandbox
install, a test):

    install_root()   LETITEDIT_ROOT, else the folder above bridge\\ (a str, normalised). Read each call, so a
                     module that reads it while it is imported sees the environment as it is then, as before.
    CODE_ROOT        the folder above bridge\\, resolved: where this copy of the code is, whatever LETITEDIT_ROOT says.
    BRIDGE           CODE_ROOT \\ bridge (the tool server's own files: data files, workers, entry scripts).
    ROOT_TEXT        the folder above bridge\\ as dirname(dirname(abspath(__file__))) gave it from a module in
                     bridge\\ (a str: not normalised, LETITEDIT_ROOT not read).
    BRIDGE_TEXT      bridge\\ the same way, as dirname(abspath(__file__)) gave it from a module in bridge\\.
"""
import os
from pathlib import Path

# bridge\letitedit\core\paths.py: four folders up is the install folder, as dirname(dirname(abspath(__file__))) was
# from a module in bridge\ (abspath, not resolve: the same text the old one-liner gave, junctions and all)
_HERE = os.path.abspath(__file__)
ROOT_TEXT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_HERE))))
BRIDGE_TEXT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
_ROOT_TEXT = ROOT_TEXT

CODE_ROOT = Path(__file__).resolve().parents[3]
BRIDGE = CODE_ROOT / 'bridge'


def install_root():
    """LETITEDIT_ROOT, else the folder above bridge\\: os.path.normpath of it, as a str."""
    return os.path.normpath(os.environ.get('LETITEDIT_ROOT') or _ROOT_TEXT)
