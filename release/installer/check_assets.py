"""Before the installer is built: every file the asset library's manifests name (assets/manifest/*.json) is in the
source folder, so the installer never ships an index that points at sounds or pictures it left out. The asset files
are local, not in git, so a fresh checkout or a worktree has only a few of them.

    python -I check_assets.py --root <source folder>

Prints one line; exits 1 (naming the first few missing files) when any is missing. Files under app/ come with the
editor and aren't checked here.
"""
import argparse
import json
import sys
from pathlib import Path


def named_files(entry):
    yield entry.get('file')
    yield from (entry.get('styles') or {}).values()
    yield from entry.get('alt_files') or []


def missing(root):
    out, total = [], 0
    for man in sorted((root / 'assets' / 'manifest').glob('*.json')):
        data = json.loads(man.read_text(encoding='utf-8-sig'))
        for entry in data.get('items') or data.get('entries') or []:
            for rel in named_files(entry):
                if not isinstance(rel, str) or not rel.startswith('assets/'):
                    continue
                total += 1
                if not (root / rel).is_file():
                    out.append(f'{man.stem}: {rel}')
    return out, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    root = Path(ap.parse_args().root)
    gone, total = missing(root)
    if gone:
        print(f'{len(gone)} of {total} asset files the library names are missing from {root} '
              f'(copy assets\\ from a full checkout): ' + '; '.join(gone[:5]))
        return 1
    print(f'asset library: all {total} named files present')
    return 0


if __name__ == '__main__':
    sys.exit(main())
