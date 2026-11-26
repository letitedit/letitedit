"""Windows' 260-character path limit (T330). Unless a PC has long paths turned on, a file whose full path reaches the
limit cannot be made or opened, and Windows only says it cannot find it. letitedit says what is wrong instead: where a
project, an export, a review or a Studio job folder is chosen (check, before anything is written), and for a file
error Windows raised over such a path (explain)."""
import os

LIMIT = 260                 # Windows' MAX_PATH, its closing character included: 259 is the longest path that works
_ENABLED_KEY = r'SYSTEM\CurrentControlSet\Control\FileSystem'
_TOO_LONG = 206             # ERROR_FILENAME_EXCED_RANGE


class PathTooLong(OSError):
    """A path letitedit would write is too long for this PC. Its text is for the person."""


def enabled():
    """True when long paths work here: Windows' LongPathsEnabled is on, or this isn't Windows."""
    if os.name != 'nt':
        return True
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _ENABLED_KEY) as key:
            return winreg.QueryValueEx(key, 'LongPathsEnabled')[0] == 1
    except OSError:
        return False


def length(path):
    """The characters in `path` as a full path, without a \\\\?\\ prefix."""
    text = os.fsdecode(path)
    if text.startswith('\\\\?\\'):
        text = '\\\\' + text[8:] if text[4:8].upper() == 'UNC\\' else text[4:]
    return len(os.path.abspath(text))


def message(characters):
    return (f"This folder's path is too long for Windows ({characters} characters; the limit is {LIMIT}). Move it "
            'somewhere shorter, or turn on Windows long paths.')


def too_long(*paths):
    """The message when the longest of these paths doesn't work on this PC, else None."""
    longest = max((length(path) for path in paths), default=0)
    return message(longest) if longest >= LIMIT and not enabled() else None


def check(*paths):
    """Raise PathTooLong when the longest of these paths, which letitedit is about to write, doesn't work here."""
    problem = too_long(*paths)
    if problem:
        raise PathTooLong(problem)


def project_files(project):
    """The longest files every project comes to have, given its .mlt path: the saves' temporary copy, its record
    beside it, and its preview's review folder."""
    folder, name = os.path.split(os.path.abspath(os.fsdecode(project)))
    stem = os.path.splitext(name)[0]
    return (os.path.join(folder, name + '.000000.tmp'),
            os.path.join(folder, stem + '.letitedit', 'new-video-request.json'),
            os.path.join(folder, stem + ' preview review', 'review-memory-for-critic.txt'))


def explain(error):
    """The same message for a file error Windows raised over a path that is too long here, else None."""
    if not isinstance(error, OSError):
        return None
    if isinstance(error, PathTooLong):
        return str(error)
    names = [name for name in (error.filename, error.filename2) if isinstance(name, (str, bytes, os.PathLike))]
    longest = max((length(name) for name in names), default=0)
    refused = getattr(error, 'winerror', None) == _TOO_LONG      # a folder's own limit is a little under a file's
    if (longest >= LIMIT or (refused and longest)) and not enabled():
        return message(longest)
    return None
