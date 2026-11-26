"""Manifest of every binary in the editor folder (C:\\LetItEdit\\app) and where its source comes from.

    python make_binary_manifest.py [app_dir] [out.tsv]

For each .exe/.dll: SHA-256, size, and the origin:
  msys2 <package> <version>   byte-identical to the file that MSYS2 package installed in C:\\msys64 (source:
                              https://github.com/msys2/MINGW-packages + https://repo.msys2.org/mingw/sources/)
  letitedit-fork             built here from C:\\LetItEdit\\src (letitedit-*.exe)
  mlt-patched                 libmltqt6.dll and libmltplus.dll built from MLT + C:\\LetItEdit\\engine-patches, and
                              libmlt-7.dll when it is the build engine-patches\\modules lists (patches 0004 and 0005)
  shotcut-26.9.27-ci          everything else: shipped in the official Shotcut 26.9.27 Windows build, whose CI builds
                              it from the sources in shotcut-src-26.9.27.txz (FFmpeg, MLT, frei0r, movit, ...)
Read-only: nothing in app_dir is changed.
"""
import hashlib
import subprocess
import sys
from pathlib import Path

APP = Path(sys.argv[1] if len(sys.argv) > 1 else r'C:\LetItEdit\app')
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).with_name('app-binaries-manifest.tsv'))
MSYS = Path(r'C:\msys64')
PACMAN = MSYS / 'usr' / 'bin' / 'pacman.exe'
CANDIDATES = [MSYS / 'mingw64' / 'bin', MSYS / 'mingw64' / 'share' / 'qt6' / 'plugins', MSYS / 'mingw64' / 'lib' / 'mlt',
              MSYS / 'mingw64' / 'lib' / 'frei0r-1', MSYS / 'mingw64' / 'share' / 'qt6' / 'qml']
PATCHED = {'libmltqt6.dll', 'libmltplus.dll'}   # in lib\mlt
PATCHED_FRAMEWORK = {'libmlt-7.dll'}             # in the app folder itself


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


ENGINE_FILES = Path(__file__).resolve().parents[2] / 'engine-patches' / 'modules'


def patched_framework(p):
    """app\\libmlt-7.dll is letitedit's build when its SHA-256 is one engine-patches\\modules lists for it
    (SHA256SUMS.txt or VERIFIED.txt); otherwise it is the stock one from the Shotcut 26.9.27 build."""
    known = set()
    for name in ('SHA256SUMS.txt', 'VERIFIED.txt'):
        f = ENGINE_FILES / name
        if f.exists():
            for line in f.read_text(encoding='utf-8-sig').splitlines():
                bits = line.split()
                if len(bits) == 2 and bits[1].lstrip('*') == p.name:
                    known.add(bits[0].lower())
    return sha(p) in known


def msys_twin(p, rel):
    names = [MSYS / 'mingw64' / 'bin' / p.name]
    parts = rel.parts
    if len(parts) > 2 and parts[0] == 'lib' and parts[1] == 'qt6':
        names.append(MSYS / 'mingw64' / 'share' / 'qt6' / 'plugins' / Path(*parts[2:]))
    if len(parts) > 2 and parts[0] == 'lib' and parts[1] == 'qml':
        names.append(MSYS / 'mingw64' / 'share' / 'qt6' / 'qml' / Path(*parts[2:]))
    for n in names:
        if n.exists() and n.stat().st_size == p.stat().st_size and sha(n) == sha(p):
            return n
    return None


def owner(path):
    try:
        posix = '/' + Path(path).relative_to(MSYS).as_posix()
        r = subprocess.run([str(PACMAN), '-Qqo', posix], capture_output=True, text=True, timeout=60)
        name = r.stdout.strip()
        if not name:
            return '?'
        v = subprocess.run([str(PACMAN), '-Q', name], capture_output=True, text=True, timeout=60).stdout.strip()
        return v or name
    except (OSError, subprocess.SubprocessError):
        return '?'


rows = []
for p in sorted(APP.rglob('*')):
    if p.suffix.lower() not in ('.dll', '.exe') or not p.is_file():
        continue
    rel = p.relative_to(APP)
    if p.name.startswith('letitedit'):
        origin = 'letitedit-fork'
    elif p.name in PATCHED and rel.parts[:2] == ('lib', 'mlt'):
        origin = 'mlt-patched (engine-patches/build_modules.sh: MLT 63218a28 + mlt-patches 0001-0003)'
    elif p.name in PATCHED_FRAMEWORK and len(rel.parts) == 1 and patched_framework(p):
        origin = 'mlt-patched (engine-patches/mlt-cache-held-item/build_libmlt.sh: MLT 63218a28 + mlt-patches 0004-0005)'
    else:
        twin = msys_twin(p, rel) if MSYS.exists() else None
        origin = f'msys2 {owner(twin)}' if twin else 'shotcut-26.9.27-ci'
    rows.append((rel.as_posix(), p.stat().st_size, sha(p), origin))

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('file\tbytes\tsha256\torigin\n')
    for r in rows:
        f.write('\t'.join(map(str, r)) + '\n')
from collections import Counter
c = Counter(r[3].split(' ')[0] for r in rows)
print(f'{len(rows)} binaries -> {OUT}: {dict(c)}')
