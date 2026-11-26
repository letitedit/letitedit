"""Where letitedit's engine processes load fonts from (A4).

The MLT Qt module in C:\\LetItEdit\\app (engine-patches\\mlt-qtext-fontdirs) loads every font file found in the folders
named by LETITEDIT_FONT_DIRS (';'-separated, searched recursively) when a text service starts in a melt process, so
text renders in the font library whatever Windows exposed at sign-in. Unset, it loads the per-user Windows font folder;
set to an empty string, it loads nothing. The editor sets the same variable for its own melt exports.

ensure() puts the default into os.environ (an existing value is kept), so every melt this Python process starts
inherits it.
"""
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge
import os
from pathlib import Path

ENV = 'LETITEDIT_FONT_DIRS'
LIBRARY = Path((_SAI_ROOT + '\\fonts\\library'))
USER_FONTS = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'Windows' / 'Fonts'


def default_dirs():
    """The default folders: the font library first, then the per-user Windows font folder (those that exist)."""
    dirs = [LIBRARY] + ([USER_FONTS] if os.environ.get('LOCALAPPDATA') else [])
    return [str(p) for p in dirs if p.is_dir()]


def ensure():
    """Set LETITEDIT_FONT_DIRS in this process's environment unless it is already set. Returns the value in use."""
    if ENV not in os.environ:
        os.environ[ENV] = ';'.join(default_dirs())
    return os.environ[ENV]


def env(base=None):
    """A copy of `base` (default os.environ) with LETITEDIT_FONT_DIRS set (an existing value is kept)."""
    out = dict(os.environ if base is None else base)
    out.setdefault(ENV, ';'.join(default_dirs()))
    return out
