"""letitedit's small files: JSON read and written safely, a file's checksum, a path kept inside a folder, and a lock
that one program holds on one file.

    read_json(path)          the JSON in a file (utf-8, a BOM allowed); a file a cloud drive hides for a moment during
                             an atomic replace is read again, up to 7 tries over about 3 s
    write_json(path, value)  written whole or not at all: a temporary file beside it, then os.replace (indent 2, UTF-8)
    digest(path)             the file's sha256, as hex
    inside(path, root)       True when path, resolved, is root or below it
    file_lock(path)          a context manager: an OS lock on one byte of path (made if missing); Windows lets it go
                             when the program ends, even by a crash. Raises RuntimeError at once when another holds it.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
import uuid
from pathlib import Path


def read_json(path):
    # a cloud drive's Windows filesystem can briefly hide a file during an atomic replace: a progress poll must not
    # give up on a healthy render because of that moment
    path = Path(path)
    for attempt in range(7):
        try:
            return json.loads(path.read_text(encoding='utf-8-sig'))
        except (FileNotFoundError, PermissionError):
            if attempt == 6:
                raise
            time.sleep(.025 * (2 ** attempt))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, path)


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def inside(path, root):
    return Path(path).resolve().is_relative_to(Path(root).resolve())


@contextlib.contextmanager
def file_lock(path, busy='Another operation owns this project/editor; wait for its job.'):
    """An OS-owned lock: released when the program ends, even by a crash."""
    import msvcrt
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as f:
        if f.tell() == 0:
            f.write(b'0')
            f.flush()
        f.seek(0)
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError(busy)
        try:
            yield
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
