"""The speech model on a PC with no GPU route understands English only (T76; 4 Nov: a plain warning, no nagging, nothing blocks).

Speech in another language then comes out as wrong words or made-up English, with nothing to show it: on French and Italian test clips,
medium.en wrote invented English, 98% and 114% of the words wrong (tests/t76/REPORT.md). So the AI hears it in every reply that rests on such a
transcript, the person sees it on a video's progress card while it listens, and a person whose Windows isn't in English is told once, up front.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
ROOT = Path(os.environ.get('LETITEDIT_ROOT') or _paths.CODE_ROOT)

# for the AI, in the replies of letitedit_words and letitedit_footage
LINE = ("Speech here was read by medium.en, which understands English only. Speech in another language comes out as wrong words or "
        "made-up English, with no error. If the words don't fit the video, tell the person that's why.")
# for the person, on the progress card while it listens
CARD = 'Listening for speech (on this PC, English only)'
# for the person, once, if their Windows isn't in English
UP_FRONT = ("Your Windows isn't in English, and speech on this PC is read by a model that understands English only. If you speak another "
            "language in your videos, its captions and word-based cuts will come out wrong. Everything else works.")


def windows_is_english():
    """From the language Windows shows itself in. LETITEDIT_QA_DISPLAY_LANGUAGE stands in for it in tests ('es', 'en'). Unknown: treated as English,
    so nobody gets a warning on a guess."""
    own = os.environ.get('LETITEDIT_QA_DISPLAY_LANGUAGE')
    if own:
        return own.lower().startswith('en')
    try:
        return ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x09
    except (AttributeError, OSError):
        return True


def _locale_name():
    buf = ctypes.create_unicode_buffer(85)
    return buf.value if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85) else ''


def _keyboard_languages():
    user32 = ctypes.windll.user32
    n = user32.GetKeyboardLayoutList(0, None)
    layouts = (ctypes.c_void_p * max(1, n))()
    n = user32.GetKeyboardLayoutList(n, layouts)
    return [(layouts[i] or 0) & 0x3FF for i in range(n)]


def may_speak_other_language():
    """Any sign the person may speak something other than English (T101): Windows shown in another language, a regional format in
    another language, or a keyboard for another language. A guess: an English Windows, region and keyboard with a Spanish speaker
    reads as English. LETITEDIT_QA_DISPLAY_LANGUAGE stands in for all three in tests. Unknown: treated as English."""
    own = os.environ.get('LETITEDIT_QA_DISPLAY_LANGUAGE')
    if own:
        return not own.lower().startswith('en')
    if not windows_is_english():
        return True
    try:
        name = _locale_name()
        if name and not name.lower().startswith('en'):
            return True
        return any(lang != 0x09 for lang in _keyboard_languages())
    except (AttributeError, OSError):
        return False


def _marker():
    return Path(os.environ.get('LETITEDIT_CACHE') or ROOT / 'cache') / 'speech-language-told.txt'


def up_front():
    """The line for a person whose Windows isn't in English, if they haven't had it; None otherwise. It counts as said once this has answered."""
    if windows_is_english():
        return None
    marker = _marker()
    if marker.exists():
        return None
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text('told\n', encoding='utf-8')
    except OSError:
        pass
    return UP_FRONT
