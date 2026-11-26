"""Source packages for the editor DLLs that are byte-identical to MSYS2 packages (from app-binaries-manifest.tsv).

    python -I msys2_sources.py list             -> msys2-sources.tsv (package, version, licences, source URL, bytes,
                                                   sha256 of the copy in release/sources when it is there) via HEAD
    python -I msys2_sources.py fetch [<dir>]    -> downloads every source archive missing from <dir> (default
                                                   release/sources, git-ignored), checks its size against the
                                                   server's, and writes msys2-sources.tsv with each one's SHA-256

MSYS2 publishes the exact source of every binary package at https://repo.msys2.org/mingw/sources/
(<pkgbase>-<version>.src.tar.zst, containing the PKGBUILD, patches and the upstream source archive). MSYS2 removes
old versions over time, so the archives are kept in release/sources for the release that ships these DLLs; the
manifest (msys2-sources.tsv) is in git.
"""
import csv
import hashlib
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCES = HERE.parent / 'sources'
MANIFEST = HERE / 'app-binaries-manifest.tsv'
PACMAN = r'C:\msys64\usr\bin\pacman.exe'
BASE = 'https://repo.msys2.org/mingw/sources/'
# pkgbase of split packages (pacman -Qi shows no base): source archive name differs from the package name
BASE_FIX = {'mingw-w64-libx264': 'mingw-w64-x264', 'mingw-w64-libwinpthread': 'mingw-w64-winpthreads',
            'mingw-w64-gettext-runtime': 'mingw-w64-gettext', 'mingw-w64-libgcc': 'mingw-w64-gcc',
            'mingw-w64-libstdc++': 'mingw-w64-gcc', 'mingw-w64-libgomp': 'mingw-w64-gcc',
            'mingw-w64-libgfortran': 'mingw-w64-gcc', 'mingw-w64-libquadmath': 'mingw-w64-gcc'}


def packages():
    pk = set()
    with open(MANIFEST, encoding='utf-8') as f:
        for row in csv.DictReader(f, delimiter='\t'):
            if row['origin'].startswith('msys2 '):
                _, name, ver = row['origin'].split(' ')
                pk.add((name, ver))
    out = []
    for name, ver in sorted(pk):
        info = subprocess.run([PACMAN, '-Qi', name], capture_output=True, text=True).stdout
        base = next((l.split(':', 1)[1].strip() for l in info.splitlines() if l.startswith('Base')), None)
        lic = next((l.split(':', 1)[1].strip() for l in info.splitlines() if l.startswith('Licenses')), '?')
        base = base or name.replace('mingw-w64-x86_64-', 'mingw-w64-')
        if base.startswith('mingw-w64-x86_64-'):
            base = 'mingw-w64-' + base[len('mingw-w64-x86_64-'):]
        base = BASE_FIX.get(base, base)
        out.append((name, ver, base, lic, f'{BASE}{base}-{ver}.src.tar.zst'))
    return out


def size(url):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=60)
        return int(r.headers.get('Content-Length') or 0)
    except Exception as e:  # noqa: BLE001 - report and go on
        return f'ERR {e}'


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def write_manifest(rows, sizes, dest):
    with open(HERE / 'msys2-sources.tsv', 'w', encoding='utf-8', newline='\n') as f:
        f.write('package\tversion\tlicences\tsource_url\tbytes\tsha256\n')
        for name, ver, base, lic, url in rows:
            local = dest / url.rsplit('/', 1)[1]
            digest = sha256(local) if local.is_file() else ''
            f.write(f'{name}\t{ver}\t{lic}\t{url}\t{sizes[url]}\t{digest}\n')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'list'
    rows = packages()
    dest = Path(sys.argv[2]) if len(sys.argv) > 2 else SOURCES
    sizes = {}
    for url in sorted({r[4] for r in rows}):
        sizes[url] = size(url)
    bad = [u for u, v in sizes.items() if not isinstance(v, int) or v == 0]
    if cmd == 'fetch':
        dest.mkdir(parents=True, exist_ok=True)
        for url in sorted(sizes):
            if url in bad:
                continue
            target = dest / url.rsplit('/', 1)[1]
            if target.is_file() and target.stat().st_size == sizes[url]:
                continue
            print('get', url, flush=True)
            part = target.with_name(target.name + '.part')
            urllib.request.urlretrieve(url, part)
            if part.stat().st_size != sizes[url]:
                raise SystemExit(f'{url}: got {part.stat().st_size} bytes, the server says {sizes[url]}')
            part.replace(target)
    write_manifest(rows, sizes, dest)
    total = sum(v for v in sizes.values() if isinstance(v, int))
    print(f'{len(rows)} packages, {len(sizes)} source archives, {total / 1e6:.0f} MB; missing: {bad or "none"}')
    if bad:
        raise SystemExit(1)
